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
    # 開発者のローカル .env（診断用に true にしていることがある）から独立させる。
    monkeypatch.setenv("DEBUG_ENDPOINTS_ENABLED", "false")
    monkeypatch.setenv("ADAPTER_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    from app.main import create_app

    return TestClient(create_app())


# ── GROWI 期待レスポンス形状（ドキュメント準拠） ──


def _growi_list_response() -> dict:
    # 実 GROWI 7.4.2 の /_api/v3/pages/list は revision を「文字列(ID)」で返す
    # （本文なし）。一覧では title はパス末尾から導出される。
    return {
        "pages": [
            {
                "_id": "65a1b2c3d4e5f60001",
                "path": "/manuals/経理/経費精算/_howto/国内出張",
                "createdAt": "2026-01-10T09:00:00.000Z",
                "updatedAt": "2026-05-29T10:30:00.000Z",
                "revision": "rev-aaa111",
            },
            {
                "_id": "65a1b2c3d4e5f60002",
                "path": "/manuals/人事/勤怠/_howto/勤怠修正",
                "createdAt": "2026-02-01T09:00:00.000Z",
                "updatedAt": "2026-05-20T08:00:00.000Z",
                "revision": "rev-bbb222",
            },
        ],
        "totalCount": 2,
        "limit": 100,
        "offset": 0,
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
    # 一覧は本文を持たないため title はパス末尾から導出される
    assert first["title"] == "国内出張"
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
    route = respx.post(f"{GROWI_BASE}/_api/v3/page").mock(
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
    route = respx.post(f"{GROWI_BASE}/_api/v3/page").mock(
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


def test_get_content_empty_id_returns_empty(client: TestClient) -> None:
    """page_id 空（新規ケース）はエラーにせず exists=False を返す。"""
    resp = client.post("/pages/get-content", json={"page_id": ""})
    assert resp.status_code == 200
    assert resp.json() == {
        "exists": False, "content": "", "title": "", "viewer_url": "", "status": ""
    }


@respx.mock
def test_get_content_returns_existing(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json=_growi_single_page_response())
    )
    resp = client.post("/pages/get-content", json={"page_id": "65a1b2c3d4e5f60001"})
    body = resp.json()
    assert body["exists"] is True
    assert "# 手順" in body["content"]
    assert body["title"] == "国内出張の経費精算"
    assert body["status"] == "published"  # 更新時に status を引き継ぐための情報


@respx.mock
def test_upsert_creates_when_no_target(client: TestClient) -> None:
    route = respx.post(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(201, json={
            "page": {"_id": "new1", "path": "/manuals/新規",
                     "updatedAt": "2026-06-10T00:00:00.000Z",
                     "revision": {"_id": "r1", "body": "x"}}})
    )
    resp = client.post("/pages/upsert", json={
        "target_page_id": "", "path": "/manuals/新規", "title": "新規",
        "content": "# 本文", "metadata": {}})
    assert resp.status_code == 200
    assert route.called  # 新規は POST /_api/v3/page


@respx.mock
def test_upsert_updates_when_target(client: TestClient) -> None:
    # 既存取得（リビジョン解決）→ PUT
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json=_growi_single_page_response())
    )
    put_route = respx.put(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(201, json={
            "page": {"_id": "65a1b2c3d4e5f60001", "path": "/manuals/x",
                     "updatedAt": "2026-06-10T00:00:00.000Z",
                     "revision": {"_id": "r2", "body": "merged"}}})
    )
    resp = client.post("/pages/upsert", json={
        "target_page_id": "65a1b2c3d4e5f60001", "path": "", "title": "更新",
        "content": "# マージ後", "metadata": {}})
    assert resp.status_code == 200
    assert put_route.called  # 更新は PUT
    sent = put_route.calls[0].request.content.decode()
    assert "マージ後" in sent


@respx.mock
def test_deprecate_pages_sets_status_and_link(client: TestClient) -> None:
    """退役: status を deprecated にし、統合先リンクを本文冒頭に足す。"""
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json=_growi_single_page_response())
    )
    put_route = respx.put(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json={
            "page": {"_id": "65a1b2c3d4e5f60001", "path": "/manuals/x",
                     "updatedAt": "2026-06-10T00:00:00.000Z",
                     "revision": {"_id": "r2", "body": "x"}}})
    )
    resp = client.post("/pages/deprecate", json={
        "page_ids": ["65a1b2c3d4e5f60001"],
        "redirect_path": "/manuals/経理/経費精算/_howto/統合先"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deprecated"] == ["65a1b2c3d4e5f60001"]
    assert body["errors"] == []
    sent = put_route.calls[0].request.content.decode()
    assert "status: deprecated" in sent
    assert "統合先" in sent  # 統合先リンクが本文に入る


@respx.mock
def test_deprecate_pages_collects_errors(client: TestClient) -> None:
    """一部が取得失敗しても他は退役し、errors に記録する（全体を止めない）。"""
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )
    resp = client.post("/pages/deprecate", json={"page_ids": ["missing"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["deprecated"] == []
    assert len(body["errors"]) == 1


@respx.mock
def test_pending_approval_returns_only_draft_pages(client: TestClient) -> None:
    """承認待ち一覧は status:draft のページだけを返す（一覧APIでなく本文取得で判定）。"""
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(200, json={
            "pages": [
                {"_id": "p-draft", "path": "/manuals/x/draft",
                 "updatedAt": "2026-06-01T00:00:00.000Z"},
                {"_id": "p-published", "path": "/manuals/x/pub",
                 "updatedAt": "2026-06-01T00:00:00.000Z"},
                {"_id": "p-nostatus", "path": "/manuals/x/none",
                 "updatedAt": "2026-06-01T00:00:00.000Z"},
            ],
            "totalCount": 3, "limit": 100, "offset": 0,
        })
    )

    def _per_page(request: httpx.Request) -> httpx.Response:
        page_id = request.url.params.get("pageId")
        bodies = {
            "p-draft": "---\ntitle: 下書き中\nstatus: draft\n---\n本文A",
            "p-published": "---\ntitle: 公開済み\nstatus: published\n---\n本文B",
            "p-nostatus": "本文C（frontmatterなし）",
        }
        paths = {
            "p-draft": "/manuals/x/draft",
            "p-published": "/manuals/x/pub",
            "p-nostatus": "/manuals/x/none",
        }
        return httpx.Response(200, json={"page": {
            "_id": page_id, "path": paths[page_id],
            "updatedAt": "2026-06-01T00:00:00.000Z",
            "revision": {"_id": f"rev-{page_id}", "body": bodies[page_id]},
        }})

    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(side_effect=_per_page)

    resp = client.get("/pages/pending-approval", params={"path_prefix": "/manuals/x"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["pages"]) == 1
    assert body["pages"][0]["id"] == "p-draft"
    assert body["pages"][0]["title"] == "下書き中"
    assert body["pages"][0]["metadata"]["status"] == "draft"


@respx.mock
def test_pending_approval_empty_when_no_drafts(client: TestClient) -> None:
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(200, json={
            "pages": [{"_id": "p1", "path": "/manuals/x/a",
                       "updatedAt": "2026-06-01T00:00:00.000Z"}],
            "totalCount": 1, "limit": 100, "offset": 0,
        })
    )
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json={"page": {
            "_id": "p1", "path": "/manuals/x/a", "updatedAt": "2026-06-01T00:00:00.000Z",
            "revision": {"_id": "r1", "body": "---\nstatus: published\n---\n本文"},
        }})
    )
    resp = client.get("/pages/pending-approval")
    assert resp.status_code == 200
    assert resp.json()["pages"] == []


@respx.mock
def test_pending_approval_skips_fetch_failures(client: TestClient) -> None:
    """本文取得に失敗したページは無視して他は返す（全体を止めない）。"""
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(200, json={
            "pages": [
                {"_id": "p-ok", "path": "/manuals/x/ok",
                 "updatedAt": "2026-06-01T00:00:00.000Z"},
                {"_id": "p-fail", "path": "/manuals/x/fail",
                 "updatedAt": "2026-06-01T00:00:00.000Z"},
            ],
            "totalCount": 2, "limit": 100, "offset": 0,
        })
    )

    def _per_page(request: httpx.Request) -> httpx.Response:
        page_id = request.url.params.get("pageId")
        if page_id == "p-fail":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json={"page": {
            "_id": "p-ok", "path": "/manuals/x/ok",
            "updatedAt": "2026-06-01T00:00:00.000Z",
            "revision": {"_id": "r-ok", "body": "---\nstatus: draft\n---\n本文"},
        }})

    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(side_effect=_per_page)
    resp = client.get("/pages/pending-approval")
    assert resp.status_code == 200
    ids = [p["id"] for p in resp.json()["pages"]]
    assert ids == ["p-ok"]


@respx.mock
def test_update_page_with_string_revision(client: TestClient) -> None:
    """GROWI が revision を文字列で返す形でも更新できる（バージョン差対応）。"""
    single = {
        "page": {
            "_id": "65a1b2c3d4e5f60001",
            "path": "/manuals/x",
            "updatedAt": "2026-06-10T00:00:00.000Z",
            "revision": "rev-str-111",  # dict でなく文字列
        }
    }
    respx.get(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json=single)
    )
    put_route = respx.put(f"{GROWI_BASE}/_api/v3/page").mock(
        return_value=httpx.Response(200, json={
            "page": {"_id": "65a1b2c3d4e5f60001", "path": "/manuals/x",
                     "updatedAt": "2026-06-10T00:00:00.000Z",
                     "revision": {"_id": "rev-str-222", "body": "更新後"}}})
    )

    resp = client.put(
        "/pages/65a1b2c3d4e5f60001",
        json={"content": "# 更新後", "metadata": {}},
    )
    assert resp.status_code == 200
    sent = put_route.calls[0].request.content.decode()
    assert "rev-str-111" in sent  # 文字列 revision がそのまま楽観ロックに使われる


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
def test_debug_raw_pages_returns_unmapped(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """debug エンドポイントは GROWI 生レスポンスをそのまま返す（既定は無効）。"""
    monkeypatch.setenv("DEBUG_ENDPOINTS_ENABLED", "true")
    get_settings.cache_clear()
    from app.main import create_app

    debug_client = TestClient(create_app())
    raw = _growi_list_response()
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(200, json=raw)
    )
    resp = debug_client.get("/debug/raw/pages")
    assert resp.status_code == 200
    # 変換されず、GROWI の生キー (_id, revision) が見える
    assert resp.json()["pages"][0]["_id"] == "65a1b2c3d4e5f60001"
    assert "revision" in resp.json()["pages"][0]


def test_debug_endpoints_disabled_by_default(client: TestClient) -> None:
    """debug エンドポイントは既定で無効（404）。診断時のみ env で有効化する。"""
    resp = client.get("/debug/raw/pages")
    assert resp.status_code == 404


@respx.mock
def test_api_key_required_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADAPTER_API_KEY 設定時は X-API-Key を要求する（/health は免除）。"""
    monkeypatch.setenv("ADAPTER_API_KEY", "secret-key")
    get_settings.cache_clear()
    from app.main import create_app

    auth_client = TestClient(create_app())
    respx.get(f"{GROWI_BASE}/_api/v3/pages/list").mock(
        return_value=httpx.Response(200, json=_growi_list_response())
    )
    respx.get(f"{GROWI_BASE}/_api/v3/healthcheck").mock(
        return_value=httpx.Response(200, json={"status": "ok"})
    )

    assert auth_client.get("/pages").status_code == 401
    assert auth_client.get("/pages", headers={"X-API-Key": "wrong"}).status_code == 401
    assert auth_client.get("/pages", headers={"X-API-Key": "secret-key"}).status_code == 200
    # 死活監視はキーなしで通る
    assert auth_client.get("/health").status_code == 200


def test_no_auth_when_key_unset(client: TestClient) -> None:
    """キー未設定（ローカル開発）は従来通り認証なし。"""
    resp = client.post("/pages/get-content", json={"page_id": ""})
    assert resp.status_code == 200
