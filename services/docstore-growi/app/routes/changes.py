"""変更検知エンドポイント。

contracts/docstore-openapi.yaml の /pages/changes を実装する。
Sync Service が定期バッチで呼び、webhook の取りこぼしを補修する。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_growi_client
from ..growi_client import GrowiClient, GrowiError
from ..mappers import _parse_dt
from ..models import ChangeEvent, ChangeEventType, ChangeList

router = APIRouter(tags=["changes"])


@router.get("/pages/changes", response_model=ChangeList)
async def get_changes(
    since: datetime = Query(..., description="この時刻以降の変更を返す"),
    include_deleted: bool = Query(default=True),
    growi: GrowiClient = Depends(get_growi_client),
) -> ChangeList:
    """指定時刻以降に変更があったページの一覧を返す。

    GROWI の recent API をページングしながら、since より新しいものを集める。
    """
    changes: list[ChangeEvent] = []
    offset = 0
    limit = 100
    newest = since

    try:
        while True:
            data = await growi.list_recent_changes(limit=limit, offset=offset)
            raw_pages = data.get("pages", []) or data.get("docs", [])
            if not raw_pages:
                break

            stop = False
            for p in raw_pages:
                updated = _parse_dt(p.get("updatedAt"))
                if updated is None:
                    continue
                if updated <= since:
                    # recent は新しい順なので、since 以前に達したら打ち切り
                    stop = True
                    break
                changes.append(
                    ChangeEvent(
                        event_type=ChangeEventType.UPDATED,
                        page_id=str(p.get("_id", "")),
                        path=str(p.get("path", "")),
                        version=_revision_id(p),
                        occurred_at=updated,
                    )
                )
                if updated > newest:
                    newest = updated

            if stop or len(raw_pages) < limit:
                break
            offset += limit
    except GrowiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ChangeList(changes=changes, next_since=newest)


def _revision_id(growi_page: dict) -> str:
    revision = growi_page.get("revision")
    if isinstance(revision, dict):
        return str(revision.get("_id", ""))
    if isinstance(revision, str):
        return revision
    return ""
