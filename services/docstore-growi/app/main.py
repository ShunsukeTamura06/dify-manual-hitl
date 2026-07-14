"""GROWI DocStore Adapter のエントリポイント。

GROWI を contracts/docstore-openapi.yaml の DocStore API として公開する。

設計原則チェック:
- 単一責任: GROWI を DocStore に見せるだけ
- 契約準拠: contracts/docstore-openapi.yaml を実装
- 設定注入: 接続情報は環境変数 (settings.py)
- Dify 非依存: Dify の存在を知らない
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .logging_setup import configure_logging
from .routes import approvals, changes, debug, meta, pages
from .settings import get_settings

# 認証を免除するパス（死活監視はキーなしで叩けるようにする）
_AUTH_EXEMPT_PATHS = frozenset({"/health"})
# ヘッダの代わりにクエリパラメータ ?key= でも認証できるパスの接頭辞。
# ブラウザの素のクリック/フォーム送信はカスタムヘッダを送れないため
# （services/sync の GROWI_WEBHOOK_TOKEN と同じ ?token= 方式を踏襲）。
# approvals.py のモジュールdocstring参照。
_QUERY_KEY_ALLOWED_PREFIXES = ("/approvals",)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("docstore-growi", settings.log_dir, settings.log_level)
    logger = logging.getLogger(__name__)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if not settings.is_configured:
            logger.warning(
                "GROWI 接続が未設定です。.env に GROWI_BASE_URL と "
                "GROWI_API_TOKEN を設定してください。"
            )
        else:
            logger.info("GROWI Adapter 起動: %s", settings.growi_base_url)
        yield

    app = FastAPI(
        title="DocStore Adapter (GROWI)",
        version="0.1.0",
        description="GROWI を DocStore API として公開する Adapter",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def require_api_key(request: Request, call_next) -> Response:
        """ADAPTER_API_KEY が設定されている場合、X-API-Key ヘッダを検証する。

        Wiki への書込・削除ができる API なので、社内ネットワークでも
        無認証で公開しない（キー未設定はローカル開発用の明示的な選択）。
        """
        key = settings.adapter_api_key
        path = request.url.path
        if key and path not in _AUTH_EXEMPT_PATHS:
            header_ok = request.headers.get("x-api-key") == key
            query_ok = path.startswith(
                _QUERY_KEY_ALLOWED_PREFIXES
            ) and request.query_params.get("key") == key
            if not (header_ok or query_ok):
                return JSONResponse(
                    status_code=401,
                    content={
                        "error_code": "unauthorized",
                        "message": "X-API-Key（/approvals は ?key= も可）が必要です",
                    },
                )
        return await call_next(request)

    app.include_router(meta.router)
    app.include_router(pages.router)
    app.include_router(changes.router)
    app.include_router(debug.router)
    app.include_router(approvals.router)

    return app


app = create_app()
