"""sync のルート層 統合テスト。

DocStore Adapter と Dify API を respx でモックし、
/sync エンドポイント → sync_engine → 各クライアントの結合を検証する。
実 DocStore / 実 Dify 不要。
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.settings import get_settings

DOCSTORE = "http://docstore.test"
DIFY = "http://dify.test"
DATASET = "ds-123"


@pytest.fixture(autouse=True)
def _configure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCSTORE_URL", DOCSTORE)
    monkeypatch.setenv("DIFY_API_BASE_URL", DIFY)
    monkeypatch.setenv("DIFY_API_KEY", "test-key")
    monkeypatch.setenv("DIFY_DATASET_ID", DATASET)
    monkeypatch.setenv("EMBED_SOURCE_HEADER", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


def _dify_docs_url() -> str:
    return f"{DIFY}/v1/datasets/{DATASET}/documents"


@respx.mock
def test_full_sync_creates_missing_documents(client: TestClient) -> None:
    # DocStore: 2 ページ
    respx.get(f"{DOCSTORE}/pages").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": [
                    {"id": "p1", "path": "/m/a", "title": "経費", "version": "v1",
                     "updated_at": "2026-05-29T10:00:00+00:00",
                     "viewer_url": f"{DOCSTORE}/m/a"},
                    {"id": "p2", "path": "/m/b", "title": "勤怠", "version": "v1",
                     "updated_at": "2026-05-29T10:00:00+00:00",
                     "viewer_url": f"{DOCSTORE}/m/b"},
                ],
                "next_cursor": None,
            },
        )
    )
    # 各ページ本文
    respx.get(f"{DOCSTORE}/pages/p1").mock(
        return_value=httpx.Response(200, json={
            "id": "p1", "path": "/m/a", "title": "経費", "content": "# 経費",
            "content_format": "markdown", "version": "v1",
            "updated_at": "2026-05-29T10:00:00+00:00", "viewer_url": f"{DOCSTORE}/m/a",
        })
    )
    respx.get(f"{DOCSTORE}/pages/p2").mock(
        return_value=httpx.Response(200, json={
            "id": "p2", "path": "/m/b", "title": "勤怠", "content": "# 勤怠",
            "content_format": "markdown", "version": "v1",
            "updated_at": "2026-05-29T10:00:00+00:00", "viewer_url": f"{DOCSTORE}/m/b",
        })
    )
    # Dify: 既存ドキュメントなし
    respx.get(_dify_docs_url()).mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    create_route = respx.post(f"{_dify_docs_url()[:-1]}/create-by-text").mock(
        return_value=httpx.Response(200, json={"document": {"id": "new"}})
    )

    resp = client.post("/sync", json={"mode": "full"})
    assert resp.status_code == 200
    result = resp.json()
    assert result["created"] == 2
    assert result["updated"] == 0
    assert result["errors"] == []
    assert create_route.call_count == 2


@respx.mock
def test_full_sync_deletes_orphan(client: TestClient) -> None:
    # DocStore: ページなし
    respx.get(f"{DOCSTORE}/pages").mock(
        return_value=httpx.Response(200, json={"pages": [], "next_cursor": None})
    )
    # Dify: 命名規則に沿う孤立ドキュメントが 1 件
    respx.get(_dify_docs_url()).mock(
        return_value=httpx.Response(200, json={
            "data": [{"id": "d-orphan", "name": "p_old::古いページ"}],
            "has_more": False,
        })
    )
    delete_route = respx.delete(f"{_dify_docs_url()}/d-orphan").mock(
        return_value=httpx.Response(204)
    )

    resp = client.post("/sync", json={"mode": "full"})
    result = resp.json()
    assert result["deleted"] == 1
    assert delete_route.called


@respx.mock
def test_full_sync_dry_run_no_writes(client: TestClient) -> None:
    respx.get(f"{DOCSTORE}/pages").mock(
        return_value=httpx.Response(200, json={
            "pages": [{"id": "p1", "path": "/m/a", "title": "経費", "version": "v1",
                       "updated_at": "2026-05-29T10:00:00+00:00",
                       "viewer_url": f"{DOCSTORE}/m/a"}],
            "next_cursor": None,
        })
    )
    respx.get(f"{DOCSTORE}/pages/p1").mock(
        return_value=httpx.Response(200, json={
            "id": "p1", "path": "/m/a", "title": "経費", "content": "# 経費",
            "content_format": "markdown", "version": "v1",
            "updated_at": "2026-05-29T10:00:00+00:00", "viewer_url": f"{DOCSTORE}/m/a",
        })
    )
    respx.get(_dify_docs_url()).mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    create_route = respx.post(f"{_dify_docs_url()[:-1]}/create-by-text").mock(
        return_value=httpx.Response(200, json={"document": {"id": "new"}})
    )

    resp = client.post("/sync", json={"mode": "full", "dry_run": True})
    result = resp.json()
    assert result["created"] == 1
    assert not create_route.called  # dry_run なので書かない


def test_sync_diff_requires_since(client: TestClient) -> None:
    resp = client.post("/sync", json={"mode": "diff"})
    assert resp.status_code == 400


@respx.mock
def test_health_both_reachable(client: TestClient) -> None:
    respx.get(f"{DOCSTORE}/info").mock(return_value=httpx.Response(200, json={}))
    respx.get(_dify_docs_url()).mock(
        return_value=httpx.Response(200, json={"data": [], "has_more": False})
    )
    resp = client.get("/health")
    body = resp.json()
    assert body["docstore_reachable"] is True
    assert body["dify_reachable"] is True
    assert body["status"] == "ok"
