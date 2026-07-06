"""DocStore Adapter クライアント。

contracts/docstore-openapi.yaml の契約を呼ぶ。
このクライアントは「DocStore 契約」しか知らない。
背後が GROWI か Obsidian か Filesystem かは一切関知しない（Wiki 非依存）。
"""

from datetime import datetime
from typing import Any

import httpx


class DocStoreError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DocStoreClient:
    """DocStore Adapter の HTTP クライアント。"""

    def __init__(self, base_url: str, timeout: float = 60.0, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        headers = {"X-API-Key": api_key} if api_key else {}
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = await self._client.get(url, params=params)
        except httpx.RequestError as exc:
            raise DocStoreError(f"DocStore への接続失敗: {exc}") from exc
        if resp.status_code >= 400:
            raise DocStoreError(
                f"DocStore API エラー: {resp.status_code} {resp.text[:200]}",
                status_code=resp.status_code,
            )
        return resp.json()

    async def ping(self) -> bool:
        try:
            await self._get("/info")
            return True
        except DocStoreError:
            return False

    async def list_all_pages(self, path_prefix: str = "") -> list[dict[str, Any]]:
        """全ページのメタを取得する（カーソルをたどって全件）。"""
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 200}
            if path_prefix:
                params["path_prefix"] = path_prefix
            if cursor:
                params["cursor"] = cursor
            data = await self._get("/pages", params=params)
            pages.extend(data.get("pages", []))
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return pages

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """本文付きでページを 1 件取得する。"""
        return await self._get(f"/pages/{page_id}")

    async def get_changes(self, since: datetime) -> dict[str, Any]:
        """since 以降の変更を取得する。"""
        return await self._get(
            "/pages/changes",
            params={"since": since.isoformat(), "include_deleted": True},
        )
