"""mappers の単体テスト。

GROWI の JSON 形状 → DocStore モデルの変換が正しいか検証する。
GROWI 実機なしで動く（純粋関数のテスト）。
"""

from app.mappers import (
    growi_to_page,
    growi_to_page_meta,
    page_to_growi_body,
)

BASE_URL = "https://growi.example.com"


def _sample_growi_page(body: str) -> dict:
    return {
        "_id": "page123",
        "path": "/manuals/経理/経費精算/_howto/国内出張",
        "createdAt": "2026-01-10T09:00:00.000Z",
        "updatedAt": "2026-05-29T10:30:00.000Z",
        "revision": {"_id": "rev456", "body": body},
    }


def test_growi_to_page_without_frontmatter() -> None:
    body = "# 国内出張の経費精算\n\n手順はこちら。"
    page = growi_to_page(_sample_growi_page(body), BASE_URL)

    assert page.id == "page123"
    assert page.path == "/manuals/経理/経費精算/_howto/国内出張"
    assert page.title == "国内出張"  # パス末尾から
    assert page.content == body
    assert page.version == "rev456"
    assert page.viewer_url == f"{BASE_URL}/manuals/経理/経費精算/_howto/国内出張"
    assert page.metadata == {}


def test_growi_to_page_with_frontmatter() -> None:
    body = (
        "---\n"
        "title: 国内出張の経費精算\n"
        "type: howto\n"
        "owner: tamura@example.com\n"
        "status: published\n"
        "canonical: true\n"
        "---\n"
        "# 本文\n\n手順はこちら。"
    )
    page = growi_to_page(_sample_growi_page(body), BASE_URL)

    assert page.title == "国内出張の経費精算"  # frontmatter 優先
    assert page.metadata["type"] == "howto"
    assert page.metadata["owner"] == "tamura@example.com"
    assert page.metadata["canonical"] is True
    # frontmatter は本文から除去される
    assert "title:" not in page.content
    assert "# 本文" in page.content


def test_growi_to_page_broken_frontmatter() -> None:
    # frontmatter が壊れていても本文は返る
    body = "---\nbad: : :\n---\n本文"
    page = growi_to_page(_sample_growi_page(body), BASE_URL)
    assert "本文" in page.content


def test_growi_to_page_meta() -> None:
    body = "---\ntitle: タイトル\nstatus: draft\n---\n本文"
    meta = growi_to_page_meta(_sample_growi_page(body), BASE_URL)

    assert meta.id == "page123"
    assert meta.title == "タイトル"
    assert meta.version == "rev456"
    assert meta.metadata["status"] == "draft"


def test_page_to_growi_body_roundtrip() -> None:
    content = "# 見出し\n\n本文。"
    metadata = {"type": "reference", "owner": "tamura@example.com"}
    body = page_to_growi_body(content, metadata)

    # frontmatter が付与され、本文も含まれる
    assert "type: reference" in body
    assert "# 見出し" in body

    # 逆変換で元に戻る
    page = growi_to_page(_sample_growi_page(body), BASE_URL)
    assert page.metadata["type"] == "reference"
    assert "# 見出し" in page.content


def test_page_to_growi_body_no_metadata() -> None:
    content = "# 見出しのみ"
    body = page_to_growi_body(content, {})
    # メタデータが無ければ frontmatter は付かない
    assert body == content


def test_page_to_growi_body_injects_title() -> None:
    # 契約の title フィールドは frontmatter に反映される（title 喪失防止）
    body = page_to_growi_body("# 本文", {"type": "howto"}, title="経費精算の手順")
    page = growi_to_page(_sample_growi_page(body), BASE_URL)
    assert page.title == "経費精算の手順"
    assert page.metadata["type"] == "howto"


def test_page_to_growi_body_title_does_not_override_frontmatter() -> None:
    # content の frontmatter に title があればそちらが優先
    content = "---\ntitle: 元のタイトル\n---\n本文"
    body = page_to_growi_body(content, {}, title="別のタイトル")
    assert body == content  # 変更なし＝元の書式のまま


def test_page_to_growi_body_merges_existing_frontmatter() -> None:
    # content に frontmatter があっても二重にならず、metadata とマージされる
    content = "---\ntitle: タイトル\ntype: howto\n---\n本文"
    body = page_to_growi_body(content, {"status": "draft"})
    assert body.count("---") == 2
    page = growi_to_page(_sample_growi_page(body), BASE_URL)
    assert page.metadata["type"] == "howto"
    assert page.metadata["status"] == "draft"
    assert page.title == "タイトル"


def test_datetime_parsing() -> None:
    page = growi_to_page(_sample_growi_page("本文"), BASE_URL)
    assert page.updated_at.year == 2026
    assert page.updated_at.month == 5
    assert page.created_at is not None
    assert page.created_at.month == 1
