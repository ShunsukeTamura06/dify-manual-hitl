"""ヘルスチェック・メタ情報エンドポイント。"""

from fastapi import APIRouter, Depends

from ..deps import get_growi_client
from ..growi_client import GrowiClient
from ..models import AdapterInfo, HealthStatus

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthStatus)
async def health(
    growi: GrowiClient = Depends(get_growi_client),
) -> HealthStatus:
    """ヘルスチェック。GROWI への到達性も確認する。"""
    reachable = await growi.ping()
    return HealthStatus(
        status="ok" if reachable else "degraded",
        wiki_reachable=reachable,
    )


@router.get("/info", response_model=AdapterInfo)
async def info() -> AdapterInfo:
    """Adapter のメタ情報を返す。"""
    return AdapterInfo()
