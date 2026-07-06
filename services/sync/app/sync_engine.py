"""同期エンジン（DocStore → Dify Knowledge の突合ロジック）。

設計原則:
- ステートレス: 状態は Dify 自身が持つ（Document 名に page_id を埋める）
- Wiki 非依存: DocStore 契約しか知らない
- 副作用の分離: クライアントを注入し、ロジックをテスト可能に

同期モード:
- full: DocStore 全ページ vs Dify 全ドキュメントを突合（孤立削除も行う）
- diff: DocStore /pages/changes の差分のみ反映

status フィルタ:
- metadata.status が exclude_statuses（既定: draft / deprecated）のページは同期しない。
  登録 Bot が作る下書きは、人が GROWI で公開（HITL 承認）するまで検索に出さない。
- 既に Dify にあるページが除外ステータスへ遷移した場合は Dify から削除する。
"""

import logging
from datetime import UTC, datetime

from .dify_client import DifyError, DifyKnowledgeClient
from .docstore_client import DocStoreClient, DocStoreError
from .models import SyncResult
from .naming import build_document_text, decode_page_id, encode_doc_name

logger = logging.getLogger(__name__)

# 同期対象外とする metadata.status（承認前の下書き・退役ページは検索に出さない）
DEFAULT_EXCLUDE_STATUSES = frozenset({"draft", "deprecated"})


class SyncEngine:
    def __init__(
        self,
        docstore: DocStoreClient,
        dify: DifyKnowledgeClient,
        embed_header: bool = True,
        exclude_statuses: frozenset[str] | set[str] = DEFAULT_EXCLUDE_STATUSES,
    ) -> None:
        self._docstore = docstore
        self._dify = dify
        self._embed_header = embed_header
        self._exclude_statuses = frozenset(exclude_statuses)

    async def _build_dify_index(self) -> dict[str, str]:
        """Dify の全ドキュメントから {page_id: document_id} マップを作る。"""
        docs = await self._dify.list_all_documents()
        index: dict[str, str] = {}
        for doc in docs:
            page_id = decode_page_id(doc.get("name", ""))
            if page_id:
                index[page_id] = doc.get("id", "")
        return index

    async def _upsert_page(
        self,
        page_id: str,
        dify_index: dict[str, str],
        result: SyncResult,
        dry_run: bool,
    ) -> None:
        """1 ページを Dify に作成 or 更新する。"""
        try:
            page = await self._docstore.get_page(page_id)
        except DocStoreError as exc:
            result.errors.append(f"get_page({page_id}) 失敗: {exc}")
            return

        # 除外ステータス（draft 等）は同期しない。既に Dify にあれば削除する
        # （公開済みが下書きへ戻された場合も検索から消すため）。
        status = str((page.get("metadata") or {}).get("status", "")).strip().lower()
        if status in self._exclude_statuses:
            existing = dify_index.get(page_id)
            if not existing:
                result.skipped += 1
                return
            if dry_run:
                result.deleted += 1
                return
            try:
                await self._dify.delete_document(existing)
                result.deleted += 1
            except DifyError as exc:
                result.errors.append(f"delete({page_id}) 失敗: {exc}")
            return

        name = encode_doc_name(page_id, page.get("title", page_id))
        text = build_document_text(page, self._embed_header)
        existing_doc_id = dify_index.get(page_id)

        if dry_run:
            if existing_doc_id:
                result.updated += 1
            else:
                result.created += 1
            return

        try:
            if existing_doc_id:
                await self._dify.update_document(existing_doc_id, name, text)
                result.updated += 1
            else:
                await self._dify.create_document(name, text)
                result.created += 1
        except DifyError as exc:
            result.errors.append(f"upsert({page_id}) 失敗: {exc}")

    async def full_sync(self, dry_run: bool = False) -> SyncResult:
        """全件突合同期。"""
        started = datetime.now(UTC)
        result = SyncResult(mode="full", started_at=started, finished_at=started)

        try:
            pages = await self._docstore.list_all_pages()
            dify_index = await self._build_dify_index()
        except (DocStoreError, DifyError) as exc:
            result.errors.append(f"初期取得失敗: {exc}")
            result.finished_at = datetime.now(UTC)
            return result

        docstore_page_ids = {p.get("id", "") for p in pages if p.get("id")}

        # 作成・更新
        for page_id in docstore_page_ids:
            await self._upsert_page(page_id, dify_index, result, dry_run)

        # 孤立削除: Dify にあるが DocStore に無い page_id
        for page_id, doc_id in dify_index.items():
            if page_id not in docstore_page_ids:
                if dry_run:
                    result.deleted += 1
                    continue
                try:
                    await self._dify.delete_document(doc_id)
                    result.deleted += 1
                except DifyError as exc:
                    result.errors.append(f"delete({page_id}) 失敗: {exc}")

        result.finished_at = datetime.now(UTC)
        return result

    async def diff_sync(self, since: datetime, dry_run: bool = False) -> SyncResult:
        """差分同期。since 以降の変更のみ反映する。"""
        started = datetime.now(UTC)
        result = SyncResult(mode="diff", started_at=started, finished_at=started)

        try:
            changes_data = await self._docstore.get_changes(since)
            dify_index = await self._build_dify_index()
        except (DocStoreError, DifyError) as exc:
            result.errors.append(f"差分取得失敗: {exc}")
            result.finished_at = datetime.now(UTC)
            return result

        changes = changes_data.get("changes", [])
        for change in changes:
            event = change.get("event_type")
            page_id = change.get("page_id", "")
            if not page_id:
                result.skipped += 1
                continue

            if event == "deleted":
                doc_id = dify_index.get(page_id)
                if not doc_id:
                    result.skipped += 1
                    continue
                if dry_run:
                    result.deleted += 1
                    continue
                try:
                    await self._dify.delete_document(doc_id)
                    result.deleted += 1
                except DifyError as exc:
                    result.errors.append(f"delete({page_id}) 失敗: {exc}")
            else:  # created / updated / moved
                await self._upsert_page(page_id, dify_index, result, dry_run)

        # 次回同期の起点
        next_since = changes_data.get("next_since")
        if isinstance(next_since, str):
            try:
                result.next_since = datetime.fromisoformat(next_since.replace("Z", "+00:00"))
            except ValueError:
                result.next_since = None

        result.finished_at = datetime.now(UTC)
        return result
