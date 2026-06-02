"""sync_engine の単体テスト。

Fake クライアントを注入し、突合ロジックをネットワークなしで検証する。
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.naming import encode_doc_name
from app.sync_engine import SyncEngine


class FakeDocStore:
    """DocStoreClient のスタブ。"""

    def __init__(self, pages: list[dict[str, Any]], changes: list[dict[str, Any]] | None = None):
        self._pages = {p["id"]: p for p in pages}
        self._changes = changes or []

    async def list_all_pages(self, path_prefix: str = "") -> list[dict[str, Any]]:
        return [
            {"id": p["id"], "title": p["title"], "path": p.get("path", "")}
            for p in self._pages.values()
        ]

    async def get_page(self, page_id: str) -> dict[str, Any]:
        return self._pages[page_id]

    async def get_changes(self, since: datetime) -> dict[str, Any]:
        return {
            "changes": self._changes,
            "next_since": datetime.now(UTC).isoformat(),
        }


class FakeDify:
    """DifyKnowledgeClient のスタブ。Dify の状態をメモリで模す。"""

    def __init__(self, docs: list[dict[str, Any]] | None = None):
        # {doc_id: {name, text}}
        self.docs: dict[str, dict[str, str]] = {}
        self._counter = 0
        for d in docs or []:
            self.docs[d["id"]] = {"name": d["name"], "text": d.get("text", "")}

    async def list_all_documents(self) -> list[dict[str, Any]]:
        return [{"id": did, "name": d["name"]} for did, d in self.docs.items()]

    async def create_document(self, name: str, text: str) -> dict[str, Any]:
        self._counter += 1
        doc_id = f"dify-{self._counter}"
        self.docs[doc_id] = {"name": name, "text": text}
        return {"document": {"id": doc_id}}

    async def update_document(self, document_id: str, name: str, text: str) -> dict[str, Any]:
        self.docs[document_id] = {"name": name, "text": text}
        return {"document": {"id": document_id}}

    async def delete_document(self, document_id: str) -> None:
        self.docs.pop(document_id, None)


def _page(pid: str, title: str, content: str = "本文") -> dict[str, Any]:
    return {
        "id": pid,
        "title": title,
        "path": f"/manuals/{title}",
        "content": content,
        "viewer_url": f"https://growi/{pid}",
        "metadata": {"status": "published"},
    }


@pytest.mark.asyncio
async def test_full_sync_creates_new_documents() -> None:
    docstore = FakeDocStore([_page("p1", "経費精算"), _page("p2", "勤怠")])
    dify = FakeDify()
    engine = SyncEngine(docstore, dify, embed_header=True)  # type: ignore[arg-type]

    result = await engine.full_sync()

    assert result.created == 2
    assert result.updated == 0
    assert result.deleted == 0
    assert result.ok
    assert len(dify.docs) == 2
    # 名前に page_id が埋め込まれている
    names = {d["name"] for d in dify.docs.values()}
    assert encode_doc_name("p1", "経費精算") in names


@pytest.mark.asyncio
async def test_full_sync_updates_existing() -> None:
    docstore = FakeDocStore([_page("p1", "経費精算", content="新しい本文")])
    dify = FakeDify([{"id": "d1", "name": encode_doc_name("p1", "経費精算")}])
    engine = SyncEngine(docstore, dify, embed_header=False)  # type: ignore[arg-type]

    result = await engine.full_sync()

    assert result.created == 0
    assert result.updated == 1
    assert dify.docs["d1"]["text"] == "新しい本文"


@pytest.mark.asyncio
async def test_full_sync_deletes_orphans() -> None:
    # DocStore には p1 のみ。Dify には p1 と（消えた）p2 がある
    docstore = FakeDocStore([_page("p1", "残る")])
    dify = FakeDify(
        [
            {"id": "d1", "name": encode_doc_name("p1", "残る")},
            {"id": "d2", "name": encode_doc_name("p2", "消えた")},
        ]
    )
    engine = SyncEngine(docstore, dify, embed_header=False)  # type: ignore[arg-type]

    result = await engine.full_sync()

    assert result.deleted == 1
    assert "d2" not in dify.docs
    assert "d1" in dify.docs


@pytest.mark.asyncio
async def test_full_sync_ignores_non_conforming_docs() -> None:
    # 手動で作られた（命名規則外の）ドキュメントは削除しない
    docstore = FakeDocStore([_page("p1", "管理対象")])
    dify = FakeDify(
        [
            {"id": "d1", "name": encode_doc_name("p1", "管理対象")},
            {"id": "manual", "name": "手動メモ"},
        ]
    )
    engine = SyncEngine(docstore, dify, embed_header=False)  # type: ignore[arg-type]

    result = await engine.full_sync()

    assert result.deleted == 0  # 手動メモは触らない
    assert "manual" in dify.docs


@pytest.mark.asyncio
async def test_full_sync_dry_run_writes_nothing() -> None:
    docstore = FakeDocStore([_page("p1", "新規")])
    dify = FakeDify()
    engine = SyncEngine(docstore, dify, embed_header=False)  # type: ignore[arg-type]

    result = await engine.full_sync(dry_run=True)

    assert result.created == 1
    assert len(dify.docs) == 0  # 実際には書いていない


@pytest.mark.asyncio
async def test_diff_sync_handles_delete_event() -> None:
    docstore = FakeDocStore(
        pages=[],
        changes=[
            {"event_type": "deleted", "page_id": "p2", "occurred_at": "2026-05-29T10:00:00Z"}
        ],
    )
    dify = FakeDify([{"id": "d2", "name": encode_doc_name("p2", "消す")}])
    engine = SyncEngine(docstore, dify, embed_header=False)  # type: ignore[arg-type]

    result = await engine.diff_sync(since=datetime(2026, 5, 29, tzinfo=UTC))

    assert result.deleted == 1
    assert "d2" not in dify.docs


@pytest.mark.asyncio
async def test_diff_sync_handles_update_event() -> None:
    docstore = FakeDocStore(
        pages=[_page("p1", "更新対象", content="更新後")],
        changes=[
            {"event_type": "updated", "page_id": "p1", "occurred_at": "2026-05-29T10:00:00Z"}
        ],
    )
    dify = FakeDify([{"id": "d1", "name": encode_doc_name("p1", "更新対象")}])
    engine = SyncEngine(docstore, dify, embed_header=False)  # type: ignore[arg-type]

    result = await engine.diff_sync(since=datetime(2026, 5, 29, tzinfo=UTC))

    assert result.updated == 1
    assert dify.docs["d1"]["text"] == "更新後"
    assert result.next_since is not None
