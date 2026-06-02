"""Dify Knowledge API クライアント。

Dify のナレッジ（データセット）に対するドキュメント CRUD をラップする。
このモジュールだけが Dify API の形式を知る。

注意: Dify のバージョンによって API レスポンス形状が異なる場合がある。
実機接続後に調整が必要になることがある（GROWI Adapter と同様）。

参考エンドポイント:
- POST   /v1/datasets/{id}/document/create-by-text
- POST   /v1/datasets/{id}/documents/{doc_id}/update-by-text
- GET    /v1/datasets/{id}/documents
- DELETE /v1/datasets/{id}/documents/{doc_id}
"""

from typing import Any

import httpx


class DifyError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DifyKnowledgeClient:
    """Dify Knowledge API クライアント。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        dataset_id: str,
        indexing_technique: str = "high_quality",
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._dataset_id = dataset_id
        self._indexing = indexing_technique
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def close(self) -> None:
        await self._client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._base_url}/v1/datasets/{self._dataset_id}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resp = await self._client.request(method, self._url(path), params=params, json=json)
        except httpx.RequestError as exc:
            raise DifyError(f"Dify への接続失敗: {exc}") from exc
        if resp.status_code >= 400:
            raise DifyError(
                f"Dify API エラー: {resp.status_code} {resp.text[:300]}",
                status_code=resp.status_code,
            )
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    async def ping(self) -> bool:
        """データセットのドキュメント一覧を 1 件だけ引いて到達確認。"""
        try:
            await self._request("GET", "/documents", params={"page": 1, "limit": 1})
            return True
        except DifyError:
            return False

    async def list_all_documents(self) -> list[dict[str, Any]]:
        """データセット内の全ドキュメントを取得する。"""
        docs: list[dict[str, Any]] = []
        page = 1
        limit = 100
        while True:
            data = await self._request(
                "GET", "/documents", params={"page": page, "limit": limit}
            )
            batch = data.get("data", [])
            docs.extend(batch)
            if not data.get("has_more") or not batch:
                break
            page += 1
        return docs

    async def create_document(self, name: str, text: str) -> dict[str, Any]:
        """テキストからドキュメントを新規作成する。"""
        payload = {
            "name": name,
            "text": text,
            "indexing_technique": self._indexing,
            "process_rule": {"mode": "automatic"},
        }
        return await self._request("POST", "/document/create-by-text", json=payload)

    async def update_document(self, document_id: str, name: str, text: str) -> dict[str, Any]:
        """既存ドキュメントをテキストで更新する。"""
        payload = {"name": name, "text": text}
        return await self._request(
            "POST", f"/documents/{document_id}/update-by-text", json=payload
        )

    async def delete_document(self, document_id: str) -> None:
        """ドキュメントを削除する。"""
        await self._request("DELETE", f"/documents/{document_id}")
