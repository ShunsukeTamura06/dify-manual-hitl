"""環境変数からの設定読み込み。

設計原則: 設定はハードコードせず、すべて環境変数経由で注入する。
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """GROWI Adapter の設定。

    すべて環境変数（または .env ファイル）から読み込む。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    growi_base_url: str = Field(
        default="",
        description="GROWI のベース URL（末尾スラッシュなし）",
    )
    growi_api_token: str = Field(
        default="",
        description="GROWI API トークン",
    )
    port: int = Field(default=8001, description="待ち受けポート")
    log_level: str = Field(default="INFO", description="ログレベル")
    manual_root_path: str = Field(
        default="/manuals",
        description="対象とするマニュアルのルートパス。空なら全ページ",
    )
    request_timeout: float = Field(
        default=30.0,
        description="GROWI API リクエストのタイムアウト秒",
    )

    @property
    def is_configured(self) -> bool:
        """GROWI 接続に必要な設定が揃っているか。"""
        return bool(self.growi_base_url) and bool(self.growi_api_token)


@lru_cache
def get_settings() -> Settings:
    """設定のシングルトンを返す。"""
    return Settings()
