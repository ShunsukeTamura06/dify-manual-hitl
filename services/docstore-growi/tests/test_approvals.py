"""/approvals（ブラウザ向け承認画面）のルートテスト。

GROWI での YAML 手編集を不要にする代替承認手段。一覧表示（GET）と
承認操作（POST）が正しく動くこと、ADAPTER_API_KEY 設定時も
キー無しでアクセスできること（意図的な認証除外）を確認する。
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.settings import get_settings

GROWI_BASE = "https://growi.test"


@pytest.fixture(autouse=True)
def _configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROWI_BASE_URL", GROWI_BASE)
    monkeypatch.setenv("GROWI_API_TOKEN", "test-token")
    monkeypatch.setenv("MANUAL_ROOT_PATH", "/manuals")
    monkeypatch.setenv("DEBUG_ENDPOINTS_ENABLED", "false")
    monkeypatch.setenv("ADAPTER_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def _draft_page_body() -> dict:
    return {
        "page": {
            "_id": "p-draft-1",
            "path": "/manuals/x/draft",
            "updatedAt": "2026-06-01T00:00:00.000Z",
            "revision": {
                "_id": "rev-1",
                "body": "---\ntitle: 下書き中の記事\nstatus: draft\n---\n本文A",
            },
        }
    }


@respx.mock
def test_approvals_list_shows_pending_pages_with_button(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": [
                    {
                        "_id": "p-draft-1",
                        "path": "/manuals/x/draft",
                        "updatedAt": "2026-06-01T00:00:00.000Z",
                    }
                ],
                "totalCount": 1,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json=_draft_page_body())
    )

    resp = client.get("/approvals")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "下書き中の記事" in resp.text
    assert "action=\"/approvals/p-draft-1\"" in resp.text
    assert "承認して公開する" in resp.text


@respx.mock
def test_approvals_list_empty_message_when_no_drafts(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(
            200, json={"pages": [], "totalCount": 0, "limit": 100, "offset": 0}
        )
    )
    resp = client.get("/approvals")
    assert resp.status_code == 200
    assert "承認待ちのページはありません" in resp.text


@respx.mock
def test_approve_page_sets_status_published(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json=_draft_page_body())
    )
    put_route = respx.put(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(
            200,
            json={
                "page": {
                    "_id": "p-draft-1",
                    "path": "/manuals/x/draft",
                    "updatedAt": "2026-06-02T00:00:00.000Z",
                    "revision": {"_id": "rev-2", "body": "x"},
                }
            },
        )
    )

    resp = client.post("/approvals/p-draft-1")
    assert resp.status_code == 200
    assert "承認しました" in resp.text

    sent = put_route.calls[0].request.content.decode()
    assert "status: published" in sent
    assert "下書き中の記事" in sent  # 内容自体は変更されない


@respx.mock
def test_approve_page_404_when_missing(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    resp = client.post("/approvals/missing")
    assert resp.status_code == 404


@respx.mock
def test_approvals_requires_key_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADAPTER_API_KEY 設定時、/approvals はキー無しだと 401、正しい ?key= なら通る。"""
    monkeypatch.setenv("ADAPTER_API_KEY", "secret-key")
    get_settings.cache_clear()
    from app.main import create_app

    auth_client = TestClient(create_app())

    # 他の JSON API は従来通りヘッダでキーを要求する（変更なし）
    assert auth_client.get("/pages").status_code == 401

    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(
            200, json={"pages": [], "totalCount": 0, "limit": 100, "offset": 0}
        )
    )
    # キー無し・間違ったキーは弾く
    assert auth_client.get("/approvals").status_code == 401
    assert auth_client.get("/approvals?key=wrong").status_code == 401
    # 正しいキーを ?key= で渡せば通る（ヘッダを送れないブラウザ想定）
    assert auth_client.get("/approvals?key=secret-key").status_code == 200


@respx.mock
def test_approvals_list_propagates_key_into_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """一覧ページの承認フォーム・戻るリンクに ?key= が引き継がれる。"""
    monkeypatch.setenv("ADAPTER_API_KEY", "secret-key")
    get_settings.cache_clear()
    from app.main import create_app

    auth_client = TestClient(create_app())
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": [
                    {
                        "_id": "p-draft-1",
                        "path": "/manuals/x/draft",
                        "updatedAt": "2026-06-01T00:00:00.000Z",
                    }
                ],
                "totalCount": 1,
                "limit": 100,
                "offset": 0,
            },
        )
    )
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json=_draft_page_body())
    )

    resp = auth_client.get("/approvals?key=secret-key")
    assert resp.status_code == 200
    assert "action=\"/approvals/p-draft-1?key=secret-key\"" in resp.text
