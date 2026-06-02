"""依存性注入（FastAPI Depends 用）。"""

from collections.abc import AsyncIterator

from .growi_client import GrowiClient
from .settings import Settings, get_settings


async def get_growi_client() -> AsyncIterator[GrowiClient]:
    """リクエストごとに GROWI クライアントを供給する。"""
    settings: Settings = get_settings()
    client = GrowiClient(
        base_url=settings.growi_base_url,
        api_token=settings.growi_api_token,
        timeout=settings.request_timeout,
    )
    try:
        yield client
    finally:
        await client.close()
