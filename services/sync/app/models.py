"""Sync Service のデータモデル。"""

from datetime import datetime

from pydantic import BaseModel, Field


class SyncResult(BaseModel):
    """同期 1 回分の結果レポート。"""

    mode: str = Field(description="full | diff")
    created: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime
    next_since: datetime | None = Field(
        default=None,
        description="diff モードの場合、次回同期に渡すべき時刻",
    )

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


class SyncRequest(BaseModel):
    """同期トリガーのリクエスト。"""

    mode: str = Field(default="full", description="full | diff")
    since: datetime | None = Field(
        default=None,
        description="diff モードの起点時刻。省略時はエラー",
    )
    dry_run: bool = Field(
        default=False,
        description="true なら Dify に書き込まず、何が起きるかだけ返す",
    )


class HealthStatus(BaseModel):
    status: str
    docstore_reachable: bool
    dify_reachable: bool
