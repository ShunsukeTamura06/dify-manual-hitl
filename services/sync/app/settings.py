"""環境変数からの設定読み込み。

設計原則: 設定はハードコードせず、すべて環境変数経由で注入する。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Sync Service の設定。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DocStore Adapter（同期元）
    docstore_url: str = Field(default="http://localhost:8001")
    docstore_api_key: str = Field(
        default="",
        description="DocStore Adapter に送る X-API-Key（Adapter 側で認証を有効にした場合）",
    )

    # Dify Knowledge API（同期先）
    dify_api_base_url: str = Field(default="http://localhost:5001")
    dify_api_key: str = Field(default="")
    dify_dataset_id: str = Field(default="")
    dify_indexing_technique: str = Field(default="high_quality")

    # 同期挙動
    embed_source_header: bool = Field(default=True)
    sync_exclude_statuses: str = Field(
        default="draft,deprecated",
        description="同期対象外とする metadata.status（カンマ区切り）。下書きを検索に出さない",
    )

    @property
    def exclude_statuses(self) -> frozenset[str]:
        """同期対象外ステータスの集合。"""
        return frozenset(
            s.strip().lower() for s in self.sync_exclude_statuses.split(",") if s.strip()
        )

    # サービス自身
    sync_api_key: str = Field(
        default="",
        description="設定すると全エンドポイント（/health 除く）で X-API-Key ヘッダを要求。"
        "空なら認証なし（ローカル開発用）",
    )
    port: int = Field(default=8002)
    log_level: str = Field(default="INFO")
    log_dir: str = Field(default="logs")
    debug_endpoints_enabled: bool = Field(default=False)
    request_timeout: float = Field(default=60.0)

    @property
    def is_configured(self) -> bool:
        """同期に必要な設定が揃っているか。"""
        return bool(self.dify_api_key) and bool(self.dify_dataset_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
