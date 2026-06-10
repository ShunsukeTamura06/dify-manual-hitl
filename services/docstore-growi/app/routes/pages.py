"""ページ CRUD エンドポイント。

contracts/docstore-openapi.yaml の /pages 系を実装する。
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_growi_client
from ..growi_client import GrowiClient, GrowiError
from ..mappers import (
    growi_to_page,
    growi_to_page_meta,
    page_to_growi_body,
)
from ..models import (
    GetContentRequest,
    GetContentResponse,
    Page,
    PageCreateRequest,
    PageList,
    PageUpdateRequest,
    UpsertRequest,
)
from ..settings import get_settings

router = APIRouter(tags=["pages"])


@router.post("/pages/get-content", response_model=GetContentResponse)
async def get_content(
    req: GetContentRequest,
    growi: GrowiClient = Depends(get_growi_client),
) -> GetContentResponse:
    """既存ページの本文を返す（マージ用）。

    page_id が空、または見つからない場合は exists=False, content="" を返す
    （登録 Bot の「新規」ケースでもエラーにせず呼べるようにするため）。
    """
    if not req.page_id:
        return GetContentResponse(exists=False)
    settings = get_settings()
    try:
        data = await growi.get_page(req.page_id)
    except GrowiError:
        return GetContentResponse(exists=False)
    page = growi_to_page(data.get("page", data), settings.growi_base_url)
    return GetContentResponse(
        exists=True, content=page.content, title=page.title, viewer_url=page.viewer_url
    )


@router.post("/pages/upsert", response_model=Page)
async def upsert_page(
    req: UpsertRequest,
    growi: GrowiClient = Depends(get_growi_client),
) -> Page:
    """target_page_id があれば更新、無ければ新規作成する（単一書込経路）。

    登録 Bot のチャットフローに IF/ELSE を持たせず一直線にするためのエンドポイント。
    """
    settings = get_settings()
    body = page_to_growi_body(req.content, req.metadata)

    if req.target_page_id:
        # 更新: 現在リビジョンを取得して PUT
        try:
            current = await growi.get_page(req.target_page_id)
        except GrowiError as exc:
            if exc.status_code == 404:
                raise HTTPException(status_code=404, detail="更新対象が見つかりません") from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        cur_page = current.get("page", current)
        rev = cur_page.get("revision")
        cur_rev = str(rev.get("_id", "")) if isinstance(rev, dict) else str(rev or "")
        try:
            data = await growi.update_page(
                page_id=req.target_page_id, body=body, revision_id=cur_rev
            )
        except GrowiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    else:
        # 新規作成
        try:
            data = await growi.create_page(path=req.path, body=body)
        except GrowiError as exc:
            if exc.status_code == 409:
                raise HTTPException(status_code=409, detail="パスが重複しています") from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return growi_to_page(data.get("page", data), settings.growi_base_url)


@router.get("/pages", response_model=PageList)
async def list_pages(
    path_prefix: str = Query(default=""),
    status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    growi: GrowiClient = Depends(get_growi_client),
) -> PageList:
    """ページ一覧（軽量版）を返す。"""
    settings = get_settings()
    effective_prefix = path_prefix or settings.manual_root_path
    offset = int(cursor) if cursor and cursor.isdigit() else 0

    try:
        data = await growi.list_pages(
            path_prefix=effective_prefix,
            limit=limit,
            offset=offset,
        )
    except GrowiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    raw_pages = data.get("pages", []) or data.get("docs", [])
    metas = [growi_to_page_meta(p, settings.growi_base_url) for p in raw_pages]

    # status フィルタ（メタデータ由来）
    if status:
        metas = [m for m in metas if m.metadata.get("status") == status]

    next_cursor = str(offset + limit) if len(raw_pages) == limit else None
    return PageList(pages=metas, next_cursor=next_cursor)


@router.get("/pages/{page_id}", response_model=Page)
async def get_page(
    page_id: str,
    growi: GrowiClient = Depends(get_growi_client),
) -> Page:
    """ページ 1 件（本文付き）を返す。"""
    settings = get_settings()
    try:
        data = await growi.get_page(page_id)
    except GrowiError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="ページが見つかりません") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    growi_page = data.get("page", data)
    return growi_to_page(growi_page, settings.growi_base_url)


@router.post("/pages", response_model=Page, status_code=201)
async def create_page(
    req: PageCreateRequest,
    growi: GrowiClient = Depends(get_growi_client),
) -> Page:
    """ページを新規作成する。"""
    settings = get_settings()
    body = page_to_growi_body(req.content, req.metadata)
    try:
        data = await growi.create_page(path=req.path, body=body)
    except GrowiError as exc:
        if exc.status_code == 409:
            raise HTTPException(status_code=409, detail="パスが重複しています") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    growi_page = data.get("page", data)
    return growi_to_page(growi_page, settings.growi_base_url)


@router.put("/pages/{page_id}", response_model=Page)
async def update_page(
    page_id: str,
    req: PageUpdateRequest,
    growi: GrowiClient = Depends(get_growi_client),
) -> Page:
    """ページを全置換更新する。"""
    settings = get_settings()

    # 現在のリビジョンを取得（楽観ロック用）
    try:
        current = await growi.get_page(page_id)
    except GrowiError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="ページが見つかりません") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    current_page = current.get("page", current)
    current_rev = ""
    revision = current_page.get("revision")
    if isinstance(revision, dict):
        current_rev = str(revision.get("_id", ""))

    # expected_version チェック（楽観ロック）
    if req.expected_version is not None and req.expected_version != current_rev:
        raise HTTPException(
            status_code=409,
            detail="バージョンが一致しません（他者が更新した可能性）",
        )

    body = page_to_growi_body(req.content, req.metadata)
    try:
        data = await growi.update_page(
            page_id=page_id,
            body=body,
            revision_id=current_rev,
        )
    except GrowiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    growi_page = data.get("page", data)
    return growi_to_page(growi_page, settings.growi_base_url)


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(
    page_id: str,
    growi: GrowiClient = Depends(get_growi_client),
) -> None:
    """ページを削除する。"""
    try:
        current = await growi.get_page(page_id)
        current_page = current.get("page", current)
        current_rev = ""
        revision = current_page.get("revision")
        if isinstance(revision, dict):
            current_rev = str(revision.get("_id", ""))
        await growi.delete_page(page_id, revision_id=current_rev)
    except GrowiError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="ページが見つかりません") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
