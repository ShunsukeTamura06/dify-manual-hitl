"""GROWI のデータ構造 ↔ DocStore モデルの変換。

GROWI 固有のレスポンス形式を、契約 (contracts/docstore-openapi.yaml) の
Page / PageMeta に変換する。逆方向（DocStore → GROWI）も担当する。

このモジュールが GROWI と DocStore の「翻訳層」。
GROWI の JSON 形状が変わってもここだけ直せばよい。
"""

from datetime import datetime
from typing import Any

import frontmatter

from .models import Page, PageMeta


def _parse_dt(value: Any) -> datetime | None:
    """GROWI の日時文字列を datetime に変換する。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        # GROWI は ISO 8601 (例: 2026-05-29T10:00:00.000Z)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _split_frontmatter(raw_body: str) -> tuple[dict[str, Any], str]:
    """Markdown 本文から frontmatter メタデータと本文を分離する。

    Returns:
        (メタデータ辞書, frontmatter を除いた本文)
    """
    try:
        post = frontmatter.loads(raw_body)
        return dict(post.metadata), post.content
    except Exception:
        # frontmatter が壊れていても本文だけは返す
        return {}, raw_body


def _title_from_path(path: str) -> str:
    """パスの末尾要素をタイトルとして使う。"""
    return path.rstrip("/").split("/")[-1] or path


def _viewer_url(base_url: str, path: str) -> str:
    """人間が開く GROWI ページ URL を組み立てる。

    注意: この URL の組み立ては GROWI 固有。Adapter の内側に閉じ込める。
    呼び出し側はこの viewer_url をそのまま使い、再加工しない。
    """
    return f"{base_url.rstrip('/')}{path}"


def _extract_revision_id(growi_page: dict[str, Any]) -> str:
    """GROWI ページから revision ID を取り出す。"""
    revision = growi_page.get("revision")
    if isinstance(revision, dict):
        return str(revision.get("_id", ""))
    if isinstance(revision, str):
        return revision
    return ""


def _extract_body(growi_page: dict[str, Any]) -> str:
    """GROWI ページから本文 Markdown を取り出す。"""
    revision = growi_page.get("revision")
    if isinstance(revision, dict):
        return str(revision.get("body", ""))
    return ""


def growi_to_page(growi_page: dict[str, Any], base_url: str) -> Page:
    """GROWI ページ → DocStore Page（本文付き）。"""
    path = str(growi_page.get("path", ""))
    raw_body = _extract_body(growi_page)
    metadata, content = _split_frontmatter(raw_body)

    return Page(
        id=str(growi_page.get("_id", "")),
        path=path,
        title=metadata.get("title") or _title_from_path(path),
        content=content,
        metadata=metadata,
        version=_extract_revision_id(growi_page),
        created_at=_parse_dt(growi_page.get("createdAt")),
        updated_at=_parse_dt(growi_page.get("updatedAt")) or datetime.now(),
        viewer_url=_viewer_url(base_url, path),
        attachments=[],
    )


def growi_to_page_meta(growi_page: dict[str, Any], base_url: str) -> PageMeta:
    """GROWI ページ → DocStore PageMeta（軽量版）。

    一覧 API では本文が無い場合があるので frontmatter は best-effort。
    """
    path = str(growi_page.get("path", ""))
    raw_body = _extract_body(growi_page)
    metadata, _ = _split_frontmatter(raw_body) if raw_body else ({}, "")

    return PageMeta(
        id=str(growi_page.get("_id", "")),
        path=path,
        title=metadata.get("title") or _title_from_path(path),
        version=_extract_revision_id(growi_page),
        updated_at=_parse_dt(growi_page.get("updatedAt")) or datetime.now(),
        viewer_url=_viewer_url(base_url, path),
        metadata=metadata,
    )


def page_to_growi_body(content: str, metadata: dict[str, Any]) -> str:
    """DocStore の content + metadata → GROWI に保存する Markdown 本文。

    メタデータを frontmatter として本文先頭に埋め込む。
    """
    if not metadata:
        return content
    post = frontmatter.Post(content, **metadata)
    return frontmatter.dumps(post)
