"""DocStore API のデータモデル。

contracts/docstore-openapi.yaml の schemas に対応する。
契約が真実。このモデルは契約を Python で表現したもの。
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ContentFormat(StrEnum):
    MARKDOWN = "markdown"


class PageStatus(StrEnum):
    PUBLISHED = "published"
    DRAFT = "draft"
    DEPRECATED = "deprecated"


class Attachment(BaseModel):
    id: str
    filename: str
    mime_type: str | None = None
    size_bytes: int | None = None
    url: str


class Page(BaseModel):
    """本文付きページ。"""

    id: str = Field(description="Adapter 固有の不透明 ID")
    path: str = Field(description="論理パス")
    title: str
    content: str = Field(description="本文（Markdown）")
    content_format: ContentFormat = ContentFormat.MARKDOWN
    metadata: dict[str, Any] = Field(default_factory=dict)
    version: str = Field(description="リビジョン識別子")
    created_at: datetime | None = None
    updated_at: datetime
    viewer_url: str = Field(description="人間がブラウザで開く URL")
    attachments: list[Attachment] = Field(default_factory=list)


class PageMeta(BaseModel):
    """一覧表示用の軽量版（本文なし）。"""

    id: str
    path: str
    title: str
    version: str
    updated_at: datetime
    viewer_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageList(BaseModel):
    pages: list[PageMeta]
    next_cursor: str | None = None


class PageCreateRequest(BaseModel):
    path: str
    title: str
    content: str
    content_format: ContentFormat = ContentFormat.MARKDOWN
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageUpdateRequest(BaseModel):
    title: str | None = None
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_version: str | None = Field(
        default=None,
        description="楽観ロック用。指定するとバージョン不一致時に 409",
    )


class UpsertRequest(BaseModel):
    """作成 or 更新を 1 エンドポイントで扱う（登録 Bot の単一書込経路用）。

    target_page_id があれば更新、無ければ path に新規作成する。
    """

    target_page_id: str = Field(default="", description="更新対象のページ ID。空なら新規作成")
    path: str = Field(description="新規作成時の配置パス")
    title: str = ""
    content: str
    content_format: ContentFormat = ContentFormat.MARKDOWN
    metadata: dict[str, Any] = Field(default_factory=dict)


class GetContentRequest(BaseModel):
    """既存ページ本文の取得（マージ用）。page_id 空は許容（新規）。"""

    page_id: str = Field(default="", description="ページ ID。空なら本文も空で返す")


class GetContentResponse(BaseModel):
    exists: bool
    content: str = ""
    title: str = ""
    viewer_url: str = ""
    status: str = Field(
        default="",
        description="既存ページの status（更新時に引き継ぐため。無ければ空）",
    )


class ChangeEventType(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    MOVED = "moved"


class ChangeEvent(BaseModel):
    event_type: ChangeEventType
    page_id: str
    path: str | None = None
    old_path: str | None = None
    version: str | None = None
    occurred_at: datetime


class ChangeList(BaseModel):
    changes: list[ChangeEvent]
    next_since: datetime


class AdapterInfo(BaseModel):
    adapter_name: str = "growi"
    adapter_version: str = "0.1.0"
    wiki_type: str = "GROWI"
    capabilities: list[str] = Field(
        default_factory=lambda: ["create", "update", "delete", "search", "attachments"]
    )


class HealthStatus(BaseModel):
    status: str
    wiki_reachable: bool


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict[str, Any] | None = None
