"""ページ CRUD エンドポイント。

contracts/docstore-openapi.yaml の /pages 系を実装する。
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import get_growi_client
from ..growi_client import GrowiClient, GrowiError
from ..mappers import (
    extract_revision_id,
    growi_to_page,
    growi_to_page_meta,
    page_to_growi_body,
)
from ..models import (
    DeprecateRequest,
    DeprecateResponse,
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


@router.post("/pages/deprecate", response_model=DeprecateResponse)
async def deprecate_pages(
    req: DeprecateRequest,
    growi: GrowiClient = Depends(get_growi_client),
) -> DeprecateResponse:
    """複数ページを退役する（status: deprecated + 統合先リンク追記）。

    重複統合の実行で、統合元ページをまとめて退役させる。原典は破壊せず、
    本文冒頭に統合先へのリンクを足し、frontmatter の status を deprecated にする。
    退役ページは sync が Dify に同期しない（検索から消える）。冪等: 既に
    deprecated でも再実行して無害。
    """
    settings = get_settings()
    result = DeprecateResponse()
    for page_id in req.page_ids:
        if not page_id:
            continue
        try:
            data = await growi.get_page(page_id)
        except GrowiError as exc:
            result.errors.append(f"{page_id}: 取得失敗 {exc}")
            continue
        growi_page = data.get("page", data)
        page = growi_to_page(growi_page, settings.growi_base_url)
        meta = dict(page.metadata)
        meta["status"] = "deprecated"
        note = ""
        if req.redirect_path:
            link = f"[{req.redirect_path}]({req.redirect_path})"
            note = f"> ⚠️ このページは {link} に統合されました。\n\n"
        # 既に退役リンクがある場合は二重付与しない（冪等）
        content = page.content if note and note in page.content else note + page.content
        body = page_to_growi_body(content, meta)
        try:
            await growi.update_page(
                page_id=page_id, body=body, revision_id=extract_revision_id(growi_page)
            )
            result.deprecated.append(page_id)
        except GrowiError as exc:
            result.errors.append(f"{page_id}: 更新失敗 {exc}")
    return result


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
        exists=True,
        content=page.content,
        title=page.title,
        viewer_url=page.viewer_url,
        status=str(page.metadata.get("status", "")),
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
    body = page_to_growi_body(req.content, req.metadata, req.title)

    if req.target_page_id:
        # 更新: 現在リビジョンを取得して PUT
        try:
            current = await growi.get_page(req.target_page_id)
        except GrowiError as exc:
            if exc.status_code == 404:
                raise HTTPException(status_code=404, detail="更新対象が見つかりません") from exc
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        cur_page = current.get("page", current)
        cur_rev = extract_revision_id(cur_page)
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
    body = page_to_growi_body(req.content, req.metadata, req.title)
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
    current_rev = extract_revision_id(current_page)

    # expected_version チェック（楽観ロック）
    if req.expected_version is not None and req.expected_version != current_rev:
        raise HTTPException(
            status_code=409,
            detail="バージョンが一致しません（他者が更新した可能性）",
        )

    body = page_to_growi_body(req.content, req.metadata, req.title)
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
        current_rev = extract_revision_id(current_page)
        await growi.delete_page(page_id, revision_id=current_rev)
    except GrowiError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="ページが見つかりません") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc
