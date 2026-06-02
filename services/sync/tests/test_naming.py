"""naming モジュールの単体テスト。"""

from app.naming import (
    build_document_text,
    build_source_header,
    decode_page_id,
    encode_doc_name,
)


def test_encode_decode_roundtrip() -> None:
    name = encode_doc_name("page123", "国内出張の経費精算")
    assert name == "page123::国内出張の経費精算"
    assert decode_page_id(name) == "page123"


def test_decode_title_with_separator() -> None:
    # タイトルに "::" が含まれても page_id は最初の区切りで取れる
    name = encode_doc_name("abc", "A::B::C")
    assert decode_page_id(name) == "abc"


def test_decode_non_conforming_name() -> None:
    # この命名規則でないドキュメントは None（同期対象外）
    assert decode_page_id("手動で作ったドキュメント") is None
    assert decode_page_id("") is None


def test_build_source_header() -> None:
    page = {
        "viewer_url": "https://growi.example.com/manuals/keihi",
        "path": "/manuals/keihi",
        "updated_at": "2026-05-29T10:00:00+00:00",
        "metadata": {"type": "howto", "status": "published"},
    }
    header = build_source_header(page)
    assert "https://growi.example.com/manuals/keihi" in header
    assert "種別:howto" in header
    assert "状態:published" in header


def test_build_document_text_with_header() -> None:
    page = {
        "content": "# 本文\n手順です。",
        "viewer_url": "https://x/y",
        "path": "/y",
        "metadata": {},
    }
    text = build_document_text(page, embed_header=True)
    assert "出典: https://x/y" in text
    assert "# 本文" in text


def test_build_document_text_without_header() -> None:
    page = {"content": "# 本文だけ", "metadata": {}}
    text = build_document_text(page, embed_header=False)
    assert text == "# 本文だけ"
