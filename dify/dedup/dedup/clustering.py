"""重複排除 提案フローのコア（文書非依存・Dify Code ノード / ローカル単体テスト共用）。

HITL「提案 → 承認 → 実行」の ①コーパス解析〜②提案生成 のうち、**決定的に処理できる部分**。

- 類似ページの候補ペア（Dify Knowledge Retrieval 等で得る）から、重複クラスタを作る（union-find）。
- 各クラスタの重なり統計を difflib で出し、確信度を「高確信=一括承認 / 要確認=個別」に振り分ける。
- 承認・実行で使う提案データ構造を組み立てる。

意味検索（候補ペアの取得）と統合本文の生成（LLM）は Dify 側の責務。本モジュールはそれらの
結果を受けて決定的に処理する純粋ロジックで、標準ライブラリのみ。`main` をそのまま Dify の
Code ノードに貼れる。設計は [docs/dedup-design.md] を参照。

文書非依存の制約: 「事例N」「第N条」等の特定マーカーに依存しない。類似は埋め込み（外部）と
文字列の重なり（difflib）だけで判断する。
"""

import difflib
from typing import Any

# クラスタを「高確信（一括承認）」と見なす最小の重なり率（最悪ペアで判定）。
HIGH_OVERLAP = 0.8

# 重複候補として拾う最小の重なり率。これ未満は無関係とみなしクラスタ化しない。
# HIGH_OVERLAP より低くし、0.5〜0.8 の「似ているが要確認」も候補に含める。
CANDIDATE_OVERLAP = 0.5

# タイトルが「一致」とみなす平均ペア類似度。実運用のタイトルは表記揺れが普通
# （「宿泊費を精算する/宿泊費精算/宿泊費の申請」等）なので完全一致は要求しない。
# 無関係なタイトル同士（実測 0.4 前後以下）を弾ける水準として 0.5。
TITLE_AGREE_OVERLAP = 0.5


def _norm(text: str) -> str:
    """重なり比較用の正規化（前後空白除去・内部空白圧縮）。"""
    return " ".join((text or "").split())


def overlap_ratio(a: str, b: str) -> float:
    """2 つの本文の文字列重なり率（0.0〜1.0）。difflib ベース・文書非依存。"""
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def cluster_min_overlap(texts: list[str]) -> float:
    """クラスタ内の最悪ペア重なり率（凝集度を保守的に測る）。"""
    if len(texts) < 2:
        return 1.0
    worst = 1.0
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            worst = min(worst, overlap_ratio(texts[i], texts[j]))
    return worst


def _build_clusters(
    ids: list[str], pairs: list[tuple[str, str, float]], min_score: float
) -> list[list[str]]:
    """候補ペアからクラスタ（サイズ 2 以上）を作る（union-find・推移閉包）。

    Args:
        ids: 全ページ ID（出力順序の基準。先頭出現順でクラスタを並べる）。
        pairs: (id_a, id_b, score) の候補ペア。score >= min_score のみ連結する。
        min_score: 連結に必要な最小スコア。

    Returns:
        ID リストのリスト（各クラスタはサイズ 2 以上、ids の出現順で安定ソート）。
    """
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for a, b, score in pairs:
        if a in parent and b in parent and score >= min_score:
            union(a, b)

    groups: dict[str, list[str]] = {}
    for i in ids:  # ids 順に辿るのでクラスタ内も安定
        groups.setdefault(find(i), []).append(i)

    clusters = [g for g in groups.values() if len(g) >= 2]
    clusters.sort(key=lambda g: ids.index(g[0]))
    return clusters


def titles_similarity(titles: list[str]) -> float:
    """タイトル群の平均ペア類似度（0.0〜1.0）を返す。

    正規化後の difflib 比較。完全一致でなく類似度で測るのは、実運用の重複ページは
    タイトルが表記揺れしているのが普通なため（一致要求だと bulk レーンが発火しない）。
    タイトルが 1 件以下（または全部空）なら 1.0（判定材料なし＝タイトルでは弾かない）。
    """
    norm = [_norm(t) for t in titles if _norm(t)]
    if len(norm) < 2:
        return 1.0
    total = 0.0
    count = 0
    for i in range(len(norm)):
        for j in range(i + 1, len(norm)):
            total += difflib.SequenceMatcher(None, norm[i], norm[j]).ratio()
            count += 1
    return total / count


def classify_confidence(min_overlap: float, titles_agree: bool) -> str:
    """クラスタの確信度を返す（"high" or "review"）。

    重なりが高く（HIGH_OVERLAP 以上）かつタイトルが揃っているなら「明白な重複」とみなす。
    """
    if min_overlap >= HIGH_OVERLAP and titles_agree:
        return "high"
    return "review"


def _coerce_pairs(pairs: Any) -> list[tuple[str, str, float]]:
    """候補ペア入力を (a, b, score) のタプル列に正規化する。

    list/tuple でも dict（a/b/score または source/target/score）でも受ける。
    """
    out: list[tuple[str, str, float]] = []
    for p in pairs or []:
        if isinstance(p, dict):
            a = p.get("a") or p.get("source") or p.get("id_a") or ""
            b = p.get("b") or p.get("target") or p.get("id_b") or ""
            score = p.get("score")
            if score is None:
                score = p.get("similarity", 0.0)
        elif isinstance(p, (list, tuple)) and len(p) >= 2:
            a, b = p[0], p[1]
            score = p[2] if len(p) >= 3 else 1.0
        else:
            continue
        if score is None:
            score = 0.0
        try:
            out.append((str(a), str(b), float(score)))
        except (TypeError, ValueError):
            continue
    return out


def build_proposals(
    pages: list[dict[str, Any]], pairs: Any, min_score: float = 0.0
) -> list[dict[str, Any]]:
    """ページ群と候補ペアから、重複統合の提案リストを組み立てる。

    Args:
        pages: {"id", "title", "path", "content"} を持つ全ページ。
        pairs: 類似候補ペア（[a, b, score] か {"a","b","score"} の列）。
        min_score: クラスタ連結に必要な最小スコア。

    Returns:
        提案 dict のリスト。各提案は cluster_id / page_ids / titles /
        representative_title / representative_path / min_overlap / confidence / lane を持つ。
    """
    by_id = {str(p.get("id", "")): p for p in pages}
    ids = [str(p.get("id", "")) for p in pages]
    coerced = _coerce_pairs(pairs)
    clusters = _build_clusters(ids, coerced, min_score)

    proposals: list[dict[str, Any]] = []
    for n, cluster in enumerate(clusters, start=1):
        members = [by_id[i] for i in cluster if i in by_id]
        texts = [str(m.get("content", "")) for m in members]
        titles = [str(m.get("title", "")) for m in members]
        min_ov = cluster_min_overlap(texts)
        titles_agree = titles_similarity(titles) >= TITLE_AGREE_OVERLAP
        confidence = classify_confidence(min_ov, titles_agree)
        # 基準ページ = 最も情報量の多い（content 最長）ページ。統合のベースにする。
        rep = max(members, key=lambda m: len(str(m.get("content", ""))))
        proposals.append(
            {
                "cluster_id": n,
                "page_ids": [str(m.get("id", "")) for m in members],
                "titles": titles,
                "representative_title": str(rep.get("title", "")),
                "representative_path": str(rep.get("path", "")),
                "min_overlap": round(min_ov, 3),
                "confidence": confidence,
                "lane": "bulk" if confidence == "high" else "individual",
            }
        )
    return proposals


def candidate_pairs_from_content(
    pages: list[dict[str, Any]], threshold: float = CANDIDATE_OVERLAP
) -> list[tuple[str, str, float]]:
    """全ページの本文を総当たりで比較し、重なりが閾値以上のペアを候補にする。

    意味検索（Dify Knowledge Retrieval）を使わずに、difflib だけで候補ペアを作る経路。
    決定的で文書非依存・stdlib のみ。O(n^2) なので中規模コーパス向け（大規模化したら
    候補生成を埋め込み検索に差し替える）。

    Args:
        pages: {"id","content"} を持つ全ページ。
        threshold: 候補とみなす最小重なり率。

    Returns:
        (id_a, id_b, overlap) のリスト。
    """
    ids = [str(p.get("id", "")) for p in pages]
    texts = [str(p.get("content", "")) for p in pages]
    pairs: list[tuple[str, str, float]] = []
    for i in range(len(pages)):
        for j in range(i + 1, len(pages)):
            ratio = overlap_ratio(texts[i], texts[j])
            if ratio >= threshold:
                pairs.append((ids[i], ids[j], ratio))
    return pairs


def build_proposals_from_content(
    pages: list[dict[str, Any]], candidate_threshold: float = CANDIDATE_OVERLAP
) -> list[dict[str, Any]]:
    """本文の総当たり比較で候補ペアを作り、そのまま提案を組み立てる（意味検索なし経路）。"""
    pairs = candidate_pairs_from_content(pages, candidate_threshold)
    return build_proposals(pages, pairs, min_score=candidate_threshold)


def main(pages: list[dict[str, Any]], pairs: Any = None) -> dict[str, list[dict[str, Any]]]:
    """Dify Code ノード用エントリ。

    `pairs` が与えられればそれを使い（Knowledge Retrieval 経路）、空なら本文総当たりで
    候補ペアを生成する（difflib 経路）。どちらも同じ提案組立に合流する。

    Args:
        pages: Wiki 全ページ（{"id","title","path","content"}）。
        pairs: 類似候補ペア（無ければ本文から自動生成）。

    Returns:
        {"proposals": [...]}。後続の対話で承認 → LLM 統合 → upsert/退役 する。
    """
    pages = pages or []
    if pairs:
        return {"proposals": build_proposals(pages, pairs)}
    return {"proposals": build_proposals_from_content(pages)}
