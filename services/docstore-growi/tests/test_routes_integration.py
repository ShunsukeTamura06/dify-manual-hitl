"""ルート層の統合テスト。

GROWI の応答を respx でモックし、FastAPI ルート → growi_client → mappers の
結合を検証する。実 GROWI 不要。

ここでモックしている JSON 形状は「GROWI のドキュメント準拠の期待形状」。
会社端末で取得した生レスポンス (diagnostics の growi-raw-*.json) と
突き合わせれば、実機との差異を一目で判定できる。
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.settings import get_settings

GROWI_BASE = "https://growi.test"


@pytest.fixture(autouse=True)
def _configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """テスト用に GROWI 接続設定を注入する。"""
    monkeypatch.setenv("GROWI_BASE_URL", GROWI_BASE)
    monkeypatch.setenv("GROWI_API_TOKEN", "test-token")
    monkeypatch.setenv("MANUAL_ROOT_PATH", "/manuals")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


# ── GROWI 期待レスポンス形状（ドキュメント準拠） ──


def _growi_list_response() -> dict:
    return {
        "pages": [
            {
                "_id": "65a1b2c3d4e5f60001",
                "path": "/manuals/経理/経費精算/_howto/国内出張",
                "createdAt": "2026-01-10T09:00:00.000Z",
                "updatedAt": "2026-05-29T10:30:00.000Z",
                "revision": {
                    "_id": "rev-aaa111",
                    "body": "---\ntitle: 国内出張の経費精算\ntype: howto\n---\n# 手順\n1. 申請",
                },
            },
            {
                "_id": "65a1b2c3d4e5f60002",
                "path": "/manuals/人事/勤怠/_howto/勤怠修正",
                "createdAt": "2026-02-01T09:00:00.000Z",
                "updatedAt": "2026-05-20T08:00:00.000Z",
                "revision": {"_id": "rev-bbb222", "body": "# 勤怠の修正"},
            },
        ]
    }


def _growi_single_page_response() -> dict:
    return {
        "page": {
            "_id": "65a1b2c3d4e5f60001",
            "path": "/manuals/経理/経費精算/_howto/国内出張",
            "createdAt": "2026-01-10T09:00:00.000Z",
            "updatedAt": "2026-05-29T10:30:00.000Z",
            "revision": {
                "_id": "rev-aaa111",
                "body": (
                    "---\n"
                    "title: 国内出張の経費精算\n"
                    "type: howto\n"
                    "owner: tamura@example.com\n"
                    "status: published\n"
                    "---\n"
                    "# 手順\n1. 申請書を作成\n2. 上長承認"
                ),
            },
        }
    }


# ── テスト ──


@respx.mock
def test_list_pages_maps_growi_response(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(200, json=_growi_list_response())
    )

    resp = client.get("/pages", params={"path_prefix": "/manuals"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["pages"]) == 2

    first = body["pages"][0]
    assert first["id"] == "65a1b2c3d4e5f60001"
    assert first["title"] == "国内出張の経費精算"  # frontmatter 由来
    assert first["version"] == "rev-aaa111"
    assert first["viewer_url"] == f"{GROWI_BASE}/manuals/経理/経費精算/_howto/国内出張"


@respx.mock
def test_get_page_returns_full_content(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json=_growi_single_page_response())
    )

    resp = client.get("/pages/65a1b2c3d4e5f60001")
    assert resp.status_code == 200
    page = resp.json()
    assert page["title"] == "国内出張の経費精算"
    assert page["metadata"]["owner"] == "tamura@example.com"
    assert page["metadata"]["status"] == "published"
    # frontmatter は本文から除去され、見出しは残る
    assert "title:" not in page["content"]
    assert "# 手順" in page["content"]


@respx.mock
def test_create_page_sends_frontmatter_body(client: TestClient) -> None:
    route = respx.post(f"{GROWI_BASE}/_api/v3/pages").mock(
        return_value=httpx.Response(
            201,
            json={
                "page": {
                    "_id": "new-id-999",
                    "path": "/manuals/新規",
                    "updatedAt": "2026-06-02T00:00:00.000Z",
                    "revision": {"_id": "rev-new", "body": "本文"},
                }
            },
        )
    )

    resp = client.post(
        "/pages",
        json={
            "path": "/manuals/新規",
            "title": "新規ページ",
            "content": "# 本文",
            "metadata": {"type": "reference", "status": "draft"},
        },
    )
    assert resp.status_code == 201
    assert route.called
    # GROWI に送った body に frontmatter が含まれる
    sent = route.calls[0].request
    sent_body = sent.content.decode()
    assert "type: reference" in sent_body
    assert "# 本文" in sent_body


@respx.mock
def test_create_page_with_frontmatter_content_no_double(client: TestClient) -> None:
    """登録 Bot の送り方を再現: content に frontmatter 込み、metadata は空。

    frontmatter が二重にならず、content がそのまま GROWI に渡ることを保証する。
    """
    route = respx.post(f"{GROWI_BASE}/_api/v3/pages").mock(
        return_value=httpx.Response(
            201,
            json={
                "page": {
                    "_id": "new-id",
                    "path": "/manuals/経理/経費精算/_howto/国内出張の経費を精算する",
                    "updatedAt": "2026-06-10T00:00:00.000Z",
                    "revision": {"_id": "rev1", "body": "x"},
                }
            },
        )
    )
    content = (
        "---\n"
        "title: 国内出張の経費を精算する\n"
        "type: howto\n"
        "status: draft\n"
        "---\n"
        "# 国内出張の経費を精算する\n\n## 概要\n手順です。"
    )

    resp = client.post(
        "/pages",
        json={
            "path": "/manuals/経理/経費精算/_howto/国内出張の経費を精算する",
            "title": "国内出張の経費を精算する",
            "content": content,
            "metadata": {},  # 空。content の frontmatter が正
        },
    )
    assert resp.status_code == 201
    sent_body = route.calls[0].request.content.decode()
    # frontmatter 区切り --- は 2 本だけ（二重frontmatterになっていない）
    assert sent_body.count("---") == 2
    assert "title: 国内出張の経費を精算する" in sent_body
    assert "status: draft" in sent_body


@respx.mock
def test_health_reports_growi_reachable(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/healthcheck").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["wiki_reachable"] is True
    assert body["status"] == "ok"


@respx.mock
def test_health_degraded_when_growi_down(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/healthcheck").mock(
        return_value=httpx.Response(500)
    )
    resp = client.get("/health")
    assert resp.json()["wiki_reachable"] is False


@respx.mock
def test_get_page_404_propagates(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    resp = client.get("/pages/missing")
    assert resp.status_code == 404


@respx.mock
def test_debug_raw_pages_returns_unmapped(client: TestClient) -> None:
    """debug エンドポイントは GROWI 生レスポンスをそのまま返す。"""
    raw = _growi_list_response()
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(200, json=raw)
    )
    resp = client.get("/debug/raw/pages")
    assert resp.status_code == 200
    # 変換されず、GROWI の生キー (_id, revision) が見える
    assert resp.json()["pages"][0]["_id"] == "65a1b2c3d4e5f60001"
    assert "revision" in resp.json()["pages"][0]
