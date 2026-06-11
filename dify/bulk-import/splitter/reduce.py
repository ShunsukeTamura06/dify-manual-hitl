"""一括取り込み Bot: 継ぎ合わせ（Reduce）。Dify Code ノード / ローカル単体テスト共用。

各ウィンドウの LLM 出力（そのウィンドウ内の完結トピックの JSON 配列）を受け取り、
ウィンドウ境界で分断されたセクションを継ぎ合わせて最終ページ一覧にする。
Map-Reduce（案A）の Reduce。

各ページに付くフラグ:
- continues_previous: このページは前ウィンドウから続くセクションの後半である。
- incomplete: このページは現ウィンドウ末尾で途切れ、次ウィンドウに続く。

設計方針: 内容欠落を防ぐことが最優先（抽出 59K 字 → 出力 5K 字の 98% 脱落バグの
解消が目的）。LLM が出すフラグが多少不整合でも「つなぐべきものはつなぐ」方向に倒し、
ページを取りこぼさない。

このファイルは標準ライブラリのみで完結しており、`main` をそのまま Dify の
Code ノードに貼り付けられる。
"""

import json
from typing import Any


def _coerce_pages(window_result: Any) -> list[dict[str, Any]]:
    """1 ウィンドウ分の LLM 出力を page dict のリストに正規化する。

    文字列（JSON、コードフェンス混じりを含む）でもパース済みオブジェクトでも受ける。
    壊れた出力は黙って空リストにして全体を止めない（耐障害性）。

    Args:
        window_result: LLM 出力（JSON 文字列 or パース済み list/dict）。

    Returns:
        title/content/continues_previous/incomplete を持つ dict のリスト。
    """
    data: Any = window_result
    if isinstance(window_result, str):
        text = window_result.strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # コードフェンスや前後の地の文が混じる場合に最初の [ ... ] を拾う。
            start, end = text.find("["), text.rfind("]")
            if start == -1 or end <= start:
                return []
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []

    pages: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        pages.append(
            {
                "title": str(item.get("title", "")).strip(),
                "content": str(item.get("content", "")),
                "continues_previous": bool(item.get("continues_previous", False)),
                "incomplete": bool(item.get("incomplete", False)),
            }
        )
    return pages


def _normalize_title(title: str) -> str:
    """タイトル比較用の正規化（前後空白除去・内部空白圧縮）。"""
    return " ".join(title.split())


def merge_window_pages(window_results: list[Any]) -> list[dict[str, str]]:
    """ウィンドウ群の LLM 出力を継ぎ合わせ、最終ページ一覧を返す。

    継ぎ合わせ条件（いずれかで前ページに連結）:
    - そのページの continues_previous が真。
    - ウィンドウ先頭のページで、直前ウィンドウ末尾が incomplete だった。
    - ウィンドウ先頭のページのタイトルが、直前ウィンドウ末尾ページのタイトルと一致する。
      （実機の gpt-4o-mini はフラグを立てないことがあるため、境界でのタイトル一致を
      フォールバックにする。同名トピックが見出しのみ＋本体に割れて別ページ化＆パス衝突する
      事故を防ぐ。文書非依存＝特定マーカーに依存しない。）

    いずれもフラグ／タイトルの不整合でも内容を落とさない方向に倒す。

    Args:
        window_results: 各ウィンドウの LLM 出力（JSON 文字列 or パース済み）のリスト。

    Returns:
        {"title", "content"} を持つ最終ページ dict のリスト（順序保持）。
    """
    merged: list[dict[str, str]] = []
    prev_dangling = False  # 直前ウィンドウの末尾ページが incomplete だったか
    for result in window_results:
        pages = _coerce_pages(result)
        for i, page in enumerate(pages):
            at_boundary = i == 0  # ウィンドウ先頭＝境界候補
            same_title = (
                at_boundary
                and bool(merged)
                and bool(page["title"])
                and _normalize_title(merged[-1]["title"]) == _normalize_title(page["title"])
            )
            join = bool(merged) and (
                page["continues_previous"] or (at_boundary and prev_dangling) or same_title
            )
            if join:
                tail = merged[-1]
                tail["content"] = f'{tail["content"].rstrip()}\n\n{page["content"].lstrip()}'
                if not tail["title"] and page["title"]:
                    tail["title"] = page["title"]
            else:
                merged.append({"title": page["title"], "content": page["content"]})
        prev_dangling = bool(pages) and pages[-1]["incomplete"]
    return merged


def main(window_results: list[Any]) -> dict[str, list[dict[str, str]]]:
    """Dify Code ノード用エントリ。

    Args:
        window_results: Iteration（各ウィンドウの LLM）出力を集約した配列。

    Returns:
        {"pages": [{"title", "content"}, ...]}。後続の Iteration で各ページを upsert する。
    """
    return {"pages": merge_window_pages(window_results)}
