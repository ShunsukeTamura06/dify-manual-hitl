"""GROWI DocStore Adapter のエントリポイント。

GROWI を contracts/docstore-openapi.yaml の DocStore API として公開する。

設計原則チェック:
- 単一責任: GROWI を DocStore に見せるだけ
- 契約準拠: contracts/docstore-openapi.yaml を実装
- 設定注入: 接続情報は環境変数 (settings.py)
- Dify 非依存: Dify の存在を知らない
"""

import logging

from fastapi import FastAPI

from .logging_setup import configure_logging
from .routes import changes, debug, meta, pages
from .settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging("docstore-growi", settings.log_dir, settings.log_level)
    logger = logging.getLogger(__name__)

    app = FastAPI(
        title="DocStore Adapter (GROWI)",
        version="0.1.0",
        description="GROWI を DocStore API として公開する Adapter",
    )

    app.include_router(meta.router)
    app.include_router(pages.router)
    app.include_router(changes.router)
    app.include_router(debug.router)

    @app.on_event("startup")
    async def _startup() -> None:
        if not settings.is_configured:
            logger.warning(
                "GROWI 接続が未設定です。.env に GROWI_BASE_URL と "
                "GROWI_API_TOKEN を設定してください。"
            )
        else:
            logger.info("GROWI Adapter 起動: %s", settings.growi_base_url)

    return app


app = create_app()
