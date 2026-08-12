"""使い方ドキュメント（docs/user-guide/）を Wiki へ投入する。

Bot に「自分自身の使い方」を答えさせるための仕組み。専用のルートやナレッジを
足すのではなく、**使い方ドキュメント自体を Wiki の記事として登録する**。
そうすれば既存の質問ルートがそのまま拾い、出典 URL・更新日表示・古さ警告と
いった仕組みも他のマニュアルと同じように効く（Wiki が正典という設計に一致）。

設計上の判断:
- **LLM を通さない**。登録 Bot 経由だと整形で内容が変わってしまうため、
  ファイルの中身をそのまま DocStore Adapter の `/pages/upsert` に渡す。
- **published で投入する**。HITL の承認ゲートは「LLM が生成した信用できない
  文章を人が確認する」ためのもの。この文書は人が書いて git で版管理され、
  管理者が明示的にこのスクリプトを実行して投入する＝その時点で人の確認を
  経ているため、`/approvals` を再度通す必要はない（frontmatter の status を
  draft に書き換えれば下書き投入もできる）。
- **冪等**。同じパスに既にページがあれば更新、無ければ新規作成する。

使い方:
    export DOCSTORE_URL=http://localhost:8001
    export DOCSTORE_API_KEY=...        # Adapter に ADAPTER_API_KEY を設定した場合のみ
    python3 tools/publish_user_guide.py           # 投入
    python3 tools/publish_user_guide.py --dry-run # 何が投入されるかだけ表示

標準ライブラリのみで動く（会社端末に追加インストール不要）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GUIDE_DIR = Path(__file__).resolve().parent.parent / "docs" / "user-guide"
TIMEOUT_SECONDS = 30


def parse_frontmatter(text: str) -> dict[str, str]:
    """Markdown 先頭の YAML frontmatter を素朴に読む。

    `key: value` の平坦な形しか使わない前提（このディレクトリの文書は
    すべてその形で書く）。YAML ライブラリに依存しないための割り切り。

    Args:
        text: Markdown 全文。

    Returns:
        frontmatter のキーと値。frontmatter が無ければ空辞書。
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta


def _request(
    url: str, api_key: str, method: str = "GET", payload: dict | None = None
) -> dict:
    """Adapter を叩いて JSON を返す。

    Args:
        url: 完全な URL。
        api_key: Adapter の API キー（空なら送らない）。
        method: HTTP メソッド。
        payload: JSON ボディ（GET なら None）。

    Returns:
        レスポンスの JSON。

    Raises:
        urllib.error.HTTPError: Adapter がエラーを返した場合。
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    headers = {"Content-Type": "application/json"} if data else {}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return json.load(resp)


def find_existing_page_id(docstore_url: str, api_key: str, path: str) -> str:
    """指定パスの既存ページ ID を返す（無ければ空文字）。

    Adapter に「パス完全一致で 1 件取る」API が無いため、path_prefix で
    引いてから完全一致を選ぶ。

    Args:
        docstore_url: Adapter のベース URL。
        api_key: Adapter の API キー。
        path: 探すページの論理パス。

    Returns:
        見つかったページ ID。見つからなければ空文字。
    """
    query = urllib.parse.urlencode({"path_prefix": path, "limit": 100})
    try:
        data = _request(f"{docstore_url}/pages?{query}", api_key)
    except urllib.error.HTTPError:
        return ""
    for page in data.get("pages", []):
        if page.get("path") == path:
            return str(page.get("id", ""))
    return ""


def publish(docstore_url: str, api_key: str, dry_run: bool = False) -> int:
    """docs/user-guide/ 配下の Markdown をすべて Wiki に投入する。

    Args:
        docstore_url: Adapter のベース URL。
        api_key: Adapter の API キー（未設定なら空文字）。
        dry_run: True なら投入せず対象だけ表示する。

    Returns:
        プロセスの終了コード（0=成功、1=1件でも失敗）。
    """
    files = sorted(GUIDE_DIR.glob("*.md"))
    if not files:
        print(f"NG: {GUIDE_DIR} に .md がありません", file=sys.stderr)
        return 1

    failed = 0
    for md in files:
        content = md.read_text(encoding="utf-8")
        meta = parse_frontmatter(content)
        path = meta.get("path", "")
        title = meta.get("title", md.stem)
        if not path:
            print(f"NG: {md.name}: frontmatter に path がありません", file=sys.stderr)
            failed += 1
            continue

        if dry_run:
            print(f"[dry-run] {path}  ({title}, status={meta.get('status', '')})")
            continue

        target_page_id = find_existing_page_id(docstore_url, api_key, path)
        payload = {
            "target_page_id": target_page_id,
            "path": path,
            "title": title,
            # 本文は frontmatter ごとそのまま渡す（Adapter 側で二重付与しない）
            "content": content,
            "metadata": {},
        }
        try:
            result = _request(
                f"{docstore_url}/pages/upsert", api_key, method="POST", payload=payload
            )
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"NG: {path}: HTTP {exc.code} {body}", file=sys.stderr)
            failed += 1
            continue
        except urllib.error.URLError as exc:
            print(f"NG: {path}: 接続失敗 {exc.reason}", file=sys.stderr)
            failed += 1
            continue

        action = "更新" if target_page_id else "新規作成"
        print(f"OK: {action} {path}  -> {result.get('viewer_url', '')}")

    if failed:
        print(f"\n{failed} 件失敗しました", file=sys.stderr)
        return 1
    if dry_run:
        print(f"\n[dry-run] {len(files)} 件が対象です（投入はしていません）。")
    else:
        print(f"\n{len(files)} 件を投入しました。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docstore-url",
        default=os.environ.get("DOCSTORE_URL", "http://localhost:8001"),
        help="DocStore Adapter のベース URL（既定: 環境変数 DOCSTORE_URL）",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DOCSTORE_API_KEY", ""),
        help="Adapter の API キー（既定: 環境変数 DOCSTORE_API_KEY）",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="投入せず対象ファイルだけ表示する"
    )
    args = parser.parse_args()
    return publish(args.docstore_url.rstrip("/"), args.api_key, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
