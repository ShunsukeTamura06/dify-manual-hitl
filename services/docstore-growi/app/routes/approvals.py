"""承認待ちページをブラウザから直接承認するための、人間向け HTML 画面。

pages.py は DocStore の JSON 契約（他の Wiki アダプタとも共通の契約）を実装する。
このモジュールはそれとは別責務（GROWI アダプタ固有の、ブラウザに直接見せる UI）
のため分離する。GROWI 上で frontmatter の YAML を手編集する承認方法は誤操作の
リスクがあるため、「一覧を見て、ボタンを押すだけ」で status を draft→published
に切り替えられるようにする。

セキュリティ上の注意（意図的な設計判断）:
- ブラウザの素のクリック（フォーム送信）はカスタムヘッダを送れないため、
  ADAPTER_API_KEY を設定している場合、このモジュール配下のパス（/approvals 以下）
  は X-API-Key ヘッダの代わりに `?key=` クエリパラメータでも認証できる
  （main.py の認証ミドルウェア参照。services/sync の GROWI_WEBHOOK_TOKEN の
  ?token= 方式と同じ考え方）。管理者が `/approvals?key=<ADAPTER_API_KEY>` の
  URL を一度共有すれば、以降の一覧表示・承認ボタンはこのモジュールが自動で
  key を引き継ぐので、利用者が毎回キーを入力する必要はない。
  ADAPTER_API_KEY が未設定なら（ローカル開発等）、他のエンドポイント同様
  キー無しでアクセスできる。
- 一覧表示（GET）は副作用が無いので安全。承認操作は POST のみで行う
  （GET の素のリンクにすると、チャット/メールのリンクプレビュー機能が誤って
  先読み・実行してしまう事故があり得るため）。
"""

import html
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from ..deps import get_growi_client
from ..growi_client import GrowiClient, GrowiError
from ..mappers import extract_revision_id, growi_to_page, page_to_growi_body
from ..settings import get_settings
from .pages import pending_approval

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _key_qs(request: Request) -> str:
    """リクエストに ?key= が付いていれば、後続リンクに引き継ぐためのクエリ文字列を返す。"""
    key = request.query_params.get("key", "")
    return ("?" + urlencode({"key": key})) if key else ""

_PAGE_HEAD = (
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    "<title>承認待ち一覧</title>"
    "<style>body{font-family:sans-serif;margin:2rem}"
    "table{border-collapse:collapse;width:100%}"
    "th,td{border:1px solid #ccc;padding:0.5rem;text-align:left}"
    "button{cursor:pointer}</style></head><body>"
)
_PAGE_TAIL = "</body></html>"


async def _set_status_published(page_id: str, growi: GrowiClient) -> None:
    """指定ページの status を published に決定的に切り替える。

    ユーザーが YAML を手編集する必要をなくすための唯一の目的の関数。
    ここで status 以外のキーは一切変更しない。
    """
    settings = get_settings()
    data = await growi.get_page(page_id)
    growi_page = data.get("page", data)
    page = growi_to_page(growi_page, settings.growi_base_url)
    meta = dict(page.metadata)
    meta["status"] = "published"
    body = page_to_growi_body(page.content, meta)
    await growi.update_page(
        page_id=page_id, body=body, revision_id=extract_revision_id(growi_page)
    )


@router.get("", response_class=HTMLResponse)
async def approvals_list(request: Request, growi: GrowiClient = Depends(get_growi_client)) -> str:
    """承認待ち（status: draft）ページを、承認ボタン付きで一覧表示する。"""
    qs = _key_qs(request)
    result = await pending_approval(path_prefix="", limit=200, growi=growi)
    if not result.pages:
        rows = "<tr><td colspan=\"3\">承認待ちのページはありません。</td></tr>"
    else:
        rows = "".join(
            "<tr><td>"
            + html.escape(p.title)
            + "</td><td><a href=\""
            + html.escape(p.viewer_url)
            + "\" target=\"_blank\" rel=\"noopener\">内容を確認（GROWI）</a></td>"
            + "<td><form method=\"post\" action=\"/approvals/"
            + html.escape(p.id)
            + html.escape(qs)
            + "\"><button type=\"submit\">承認して公開する</button></form></td></tr>"
            for p in result.pages
        )
    return (
        _PAGE_HEAD
        + "<h1>承認待ち一覧</h1>"
        + "<p>内容を確認してから「承認して公開する」を押してください。"
        + "内容を直したい場合はGROWIで編集してください。</p>"
        + "<table><tr><th>タイトル</th><th>内容確認</th><th>承認</th></tr>"
        + rows
        + "</table>"
        + _PAGE_TAIL
    )


@router.post("/{page_id}", response_class=HTMLResponse)
async def approve_page(
    page_id: str, request: Request, growi: GrowiClient = Depends(get_growi_client)
) -> str:
    """承認待ち一覧のボタン送信を受けて、status を published にする。"""
    try:
        await _set_status_published(page_id, growi)
    except GrowiError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="ページが見つかりません") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return (
        _PAGE_HEAD
        + "<p>承認しました。公開されるまで同期を待ってください。</p>"
        + "<p><a href=\"/approvals"
        + html.escape(_key_qs(request))
        + "\">一覧に戻る</a></p>"
        + _PAGE_TAIL
    )
