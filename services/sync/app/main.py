"""Sync Service のエントリポイント。

DocStore Adapter → Dify Knowledge への同期を提供する。

設計原則チェック:
- 単一責任: 同期だけ。LLM もユーザーも知らない
- Wiki 非依存: DocStore 契約しか知らない（GROWI を直接知らない）
- 設定注入: 接続情報は環境変数
- ステートレス: 同期状態は Dify 自身が持つ（Document 名に page_id 埋込）

エンドポイント:
- POST /sync    : 同期トリガー（full / diff、dry_run 対応）
- GET  /health  : DocStore と Dify への到達確認
- GET  /info    : サービス情報
"""

import logging

from fastapi import FastAPI, HTTPException

from .dify_client import DifyKnowledgeClient
from .docstore_client import DocStoreClient
from .models import HealthStatus, SyncRequest, SyncResult
from .settings import get_settings
from .sync_engine import SyncEngine


def _make_docstore() -> DocStoreClient:
    s = get_settings()
    return DocStoreClient(base_url=s.docstore_url, timeout=s.request_timeout)


def _make_dify() -> DifyKnowledgeClient:
    s = get_settings()
    return DifyKnowledgeClient(
        base_url=s.dify_api_base_url,
        api_key=s.dify_api_key,
        dataset_id=s.dify_dataset_id,
        indexing_technique=s.dify_indexing_technique,
        timeout=s.request_timeout,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    logger = logging.getLogger(__name__)

    app = FastAPI(
        title="Sync Service (DocStore → Dify Knowledge)",
        version="0.1.0",
        description="Wiki（DocStore）を Dify Knowledge に同期する。Wiki 非依存。",
    )

    @app.on_event("startup")
    async def _startup() -> None:
        if not settings.is_configured:
            logger.warning(
                "Dify 接続が未設定です。.env に DIFY_API_KEY と "
                "DIFY_DATASET_ID を設定してください。"
            )

    @app.post("/sync", response_model=SyncResult)
    async def sync(req: SyncRequest) -> SyncResult:
        if req.mode not in ("full", "diff"):
            raise HTTPException(status_code=400, detail="mode は full か diff")
        if req.mode == "diff" and req.since is None:
            raise HTTPException(status_code=400, detail="diff モードは since 必須")

        docstore = _make_docstore()
        dify = _make_dify()
        try:
            engine = SyncEngine(docstore, dify, embed_header=settings.embed_source_header)
            if req.mode == "full":
                return await engine.full_sync(dry_run=req.dry_run)
            assert req.since is not None
            return await engine.diff_sync(req.since, dry_run=req.dry_run)
        finally:
            await docstore.close()
            await dify.close()

    @app.get("/health", response_model=HealthStatus)
    async def health() -> HealthStatus:
        docstore = _make_docstore()
        dify = _make_dify()
        try:
            ds_ok = await docstore.ping()
            dify_ok = await dify.ping()
        finally:
            await docstore.close()
            await dify.close()
        return HealthStatus(
            status="ok" if (ds_ok and dify_ok) else "degraded",
            docstore_reachable=ds_ok,
            dify_reachable=dify_ok,
        )

    @app.get("/info")
    async def info() -> dict[str, str]:
        return {
            "service": "sync",
            "version": "0.1.0",
            "docstore_url": settings.docstore_url,
            "dify_dataset_id": settings.dify_dataset_id or "(未設定)",
        }

    return app


app = create_app()
