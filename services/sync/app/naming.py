"""Dify Document 名への page_id 埋め込みと、本文ヘッダ生成。

設計判断（docs より）:
- Dify を状態保持先にするため、Document 名に DocStore の page_id を埋め込む。
- これにより外部 DB なしで page_id ↔ document_id の対応を復元できる（ステートレス）。

名前形式:  "{page_id}::{title}"
  page_id は GROWI の ObjectId 等、"::" を含まない不透明文字列を想定。
"""

from typing import Any

_SEP = "::"


def encode_doc_name(page_id: str, title: str) -> str:
    """page_id と title から Dify Document 名を作る。"""
    # title 内に区切り文字があっても decode 側は最初の SEP で割るので安全
    return f"{page_id}{_SEP}{title}"


def decode_page_id(doc_name: str) -> str | None:
    """Dify Document 名から page_id を取り出す。

    この命名規則で作られていない（= 手動で入れた等の）ドキュメントは
    None を返す。同期対象外として扱う。
    """
    if _SEP not in doc_name:
        return None
    page_id = doc_name.split(_SEP, 1)[0]
    return page_id or None


def build_source_header(page: dict[str, Any]) -> str:
    """ページ本文の先頭に付ける出典ヘッダ（引用用）。

    retrieval 時にこのヘッダを含むチャンクが引かれると、
    LLM が viewer_url を引用に使える。
    """
    meta = page.get("metadata") or {}
    lines = [
        f"> 出典: {page.get('viewer_url', '')}",
        f"> パス: {page.get('path', '')}",
    ]
    extras = []
    if meta.get("type"):
        extras.append(f"種別:{meta['type']}")
    if meta.get("status"):
        extras.append(f"状態:{meta['status']}")
    if page.get("updated_at"):
        extras.append(f"最終更新:{page['updated_at']}")
    if extras:
        lines.append("> " + " / ".join(extras))
    return "\n".join(lines)


def build_document_text(page: dict[str, Any], embed_header: bool) -> str:
    """Dify に送る本文テキストを組み立てる。"""
    content = page.get("content", "")
    if not embed_header:
        return content
    header = build_source_header(page)
    return f"{header}\n\n{content}"
