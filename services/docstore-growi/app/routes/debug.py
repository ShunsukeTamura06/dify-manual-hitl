"""診断用エンドポイント。

GROWI の「生レスポンス」を変換せずそのまま返す。
会社端末でバージョン差により mappers が動かないとき、
このレスポンスを診断バンドルに含めて持ち帰れば、開発側で形状を確認して修正できる。

注意:
- 返すのは GROWI の応答ボディのみ。リクエストに付けた access_token は応答に含まれない。
- マニュアル本文（生値）を含む。会社データを持ち出す前提の運用であること。
- settings.debug_endpoints_enabled で無効化できる。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_growi_client
from ..growi_client import GrowiClient, GrowiError
from ..settings import get_settings

router = APIRouter(tags=["debug"], prefix="/debug")


def _guard() -> None:
    if not get_settings().debug_endpoints_enabled:
        raise HTTPException(status_code=404, detail="debug エンドポイントは無効です")


@router.get("/raw/pages")
async def raw_list_pages(
    path_prefix: str = Query(default=""),
    limit: int = Query(default=20),
    growi: GrowiClient = Depends(get_growi_client),
) -> dict[str, Any]:
    """GROWI のページ一覧 生レスポンス。"""
    _guard()
    settings = get_settings()
    prefix = path_prefix or settings.manual_root_path
    try:
        return await growi.list_pages(path_prefix=prefix, limit=limit)
    except GrowiError as exc:
        return {"_error": str(exc), "_status_code": exc.status_code}


@router.get("/raw/page/{page_id}")
async def raw_get_page(
    page_id: str,
    growi: GrowiClient = Depends(get_growi_client),
) -> dict[str, Any]:
    """GROWI の単一ページ 生レスポンス。"""
    _guard()
    try:
        return await growi.get_page(page_id)
    except GrowiError as exc:
        return {"_error": str(exc), "_status_code": exc.status_code}


@router.get("/raw/recent")
async def raw_recent(
    limit: int = Query(default=20),
    growi: GrowiClient = Depends(get_growi_client),
) -> dict[str, Any]:
    """GROWI の最近更新ページ 生レスポンス（差分同期の検証用）。"""
    _guard()
    try:
        return await growi.list_recent_changes(limit=limit)
    except GrowiError as exc:
        return {"_error": str(exc), "_status_code": exc.status_code}
