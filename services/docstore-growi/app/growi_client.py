"""GROWI REST API クライアント。

GROWI v3 API をラップする。このモジュールだけが GROWI の API 形式を知る。
（設計原則: GROWI 固有の知識をこのファイルに閉じ込め、外に漏らさない）

参考: GROWI API は /_api/v3/ 系。認証は access_token クエリパラメータ。
GROWI のバージョンによって差異があるため、エンドポイントは調整が必要な場合あり。
"""

from typing import Any

import httpx


class GrowiError(Exception):
    """GROWI API 呼び出しエラー。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GrowiClient:
    """GROWI v3 API クライアント。"""

    def __init__(self, base_url: str, api_token: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    def _params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"access_token": self._api_token}
        if extra:
            params.update(extra)
        return params

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = await self._client.request(
                method,
                url,
                params=self._params(params),
                json=json,
            )
        except httpx.RequestError as exc:
            raise GrowiError(f"GROWI への接続に失敗: {exc}") from exc

        if resp.status_code >= 400:
            raise GrowiError(
                f"GROWI API エラー: {resp.status_code} {resp.text[:200]}",
                status_code=resp.status_code,
            )
        data: dict[str, Any] = resp.json()
        return data

    # ── ヘルスチェック ──

    async def ping(self) -> bool:
        """GROWI に到達できるか確認する。"""
        try:
            await self._request("GET", "/_api/v3/healthcheck")
            return True
        except GrowiError:
            return False

    # ── ページ操作 ──

    async def list_pages(
        self,
        path_prefix: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """指定パス配下のページ一覧を取得する。

        GROWI の /_api/v3/pages/list は path 配下を返す。
        """
        params = {
            "path": path_prefix or "/",
            "limit": limit,
            "offset": offset,
        }
        return await self._request("GET", "/_api/v3/pages/list", params=params)

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """ページ ID で 1 ページ取得する。"""
        return await self._request("GET", "/_api/v3/page", params={"pageId": page_id})

    async def get_page_by_path(self, path: str) -> dict[str, Any]:
        """パスで 1 ページ取得する。"""
        return await self._request("GET", "/_api/v3/page", params={"path": path})

    async def create_page(
        self,
        path: str,
        body: str,
    ) -> dict[str, Any]:
        """ページを新規作成する。

        GROWI 7.4.2 では作成は単数形 /_api/v3/page（複数形は 404）。
        """
        payload = {"path": path, "body": body}
        return await self._request("POST", "/_api/v3/page", json=payload)

    async def update_page(
        self,
        page_id: str,
        body: str,
        revision_id: str,
    ) -> dict[str, Any]:
        """ページを更新する。

        GROWI は楽観ロックのため revision_id を要求する。
        """
        payload = {
            "pageId": page_id,
            "body": body,
            "revisionId": revision_id,
        }
        return await self._request("PUT", "/_api/v3/page", json=payload)

    async def delete_page(self, page_id: str, revision_id: str) -> dict[str, Any]:
        """ページを削除する。

        GROWI 7.4.2 は pageId→revisionId のマップ形式を要求する
        （{pageId, revisionId} 形式だと 400）。
        """
        payload = {"pageIdToRevisionIdMap": {page_id: revision_id}}
        return await self._request("POST", "/_api/v3/pages/delete", json=payload)

    async def list_recent_changes(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """最近更新されたページを取得する（同期の差分検知に使う）。"""
        params = {"limit": limit, "offset": offset}
        return await self._request("GET", "/_api/v3/pages/recent", params=params)
