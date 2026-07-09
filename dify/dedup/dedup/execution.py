"""重複排除の実行フェーズ（承認 → 統合 → 退役）の決定的コア。

提示フェーズ（[clustering.py]）が出した提案を、ユーザーの承認を受けて実行する。
このモジュールは決定的に処理できる部分:
- 承認の判定（ユーザーの返答が「承認」か）
- 統合ジョブの組み立て（提案 + 再取得した本文 → 各クラスタの統合入力・退役対象）
- 完全性チェック（統合本文に元ページの主張が残っているか。欠落の警告）

統合本文の生成そのものは LLM（Dify ノード）、統合先の更新と退役は HTTP（DocStore
Adapter の /pages/upsert と /pages/deprecate）が担う。本モジュールは標準ライブラリのみで、
`main` をそのまま Dify の Code ノードに貼れる。設計は [docs/dedup-design.md]。

安全性の原則（docs/dedup-design.md）:
- 高確信（lane=bulk）のクラスタのみ自動統合の対象にする（曖昧なものは提示のみ）。
- 統合先は draft で作る（人が再確認して公開）。退役は deprecated 化（即削除しない）。
- 冪等: 単独ページや既に統合済みは対象にならない。欠落ゼロを完全性チェックで監視。
"""

import difflib
from typing import Any

# 承認とみなすキーワード（部分一致）。曖昧な返答は承認扱いにしない（安全側）。
_APPROVAL_KEYWORDS = ("承認", "統合して", "統合する", "実行", "まとめて", "ok", "はい")

# 完全性チェック: 元ページの行がこの割合以上、統合本文に残っていれば OK とみなす。
COMPLETENESS_THRESHOLD = 0.7


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def is_approval(query: str) -> bool:
    """ユーザーの返答が統合の承認かを判定する（決定的）。

    「承認」「統合して」「実行」等の明示語を含むかで判断する。曖昧な返答
    （質問・修正指示など）は False にして、勝手に実行しない。
    """
    q = (query or "").strip().lower()
    if not q:
        return False
    return any(k in q for k in _APPROVAL_KEYWORDS)


def select_executable(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """自動統合の対象にする提案（高確信 = lane が bulk）だけを選ぶ。

    曖昧・要確認（lane=individual）は人の個別判断が要るので実行対象にしない。
    """
    return [p for p in (proposals or []) if p.get("lane") == "bulk"]


def prepare_merge_jobs(
    proposals: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """提案 + 再取得した本文から、クラスタごとの統合ジョブを組み立てる。

    Args:
        proposals: 承認対象の提案（select_executable 済みを想定）。
        pages: 現在の Wiki ページ（{"id","title","path","content"}）。承認ターンで
            再取得したもの。提案時から変わっていても最新で処理する。

    Returns:
        統合ジョブのリスト。各ジョブ:
        - representative_id / representative_path / representative_title: 統合先ページ
        - merge_input: LLM に渡す統合元テキスト（全メンバーの title + content）
        - member_contents: 完全性チェック用の元本文リスト
        - deprecated_ids: 統合先以外の退役対象ページ ID
        現存しないページ・単独になったクラスタは安全側で除外する（冪等）。
    """
    by_id = {str(p.get("id", "")): p for p in (pages or [])}
    jobs: list[dict[str, Any]] = []
    for prop in proposals or []:
        page_ids = [str(i) for i in prop.get("page_ids", [])]
        members = [by_id[i] for i in page_ids if i in by_id]
        if len(members) < 2:
            # 対象が消えた/単独化 → 統合不要（冪等・安全）
            continue
        rep_id = str(prop.get("representative_id", ""))
        if rep_id not in by_id:
            # 基準ページが消えていれば最長本文を選び直す
            rep = max(members, key=lambda m: len(str(m.get("content", ""))))
            rep_id = str(rep.get("id", ""))
        rep = by_id[rep_id]
        member_contents = [str(m.get("content", "")) for m in members]
        merge_input = "\n\n".join(
            f"## {m.get('title', '')}\n{m.get('content', '')}" for m in members
        )
        jobs.append(
            {
                "representative_id": rep_id,
                "representative_path": str(rep.get("path", "")),
                "representative_title": str(rep.get("title", "")),
                "merge_input": merge_input,
                "member_contents": member_contents,
                "deprecated_ids": [i for i in page_ids if i != rep_id and i in by_id],
            }
        )
    return jobs


def check_completeness(
    merged_content: str, member_contents: list[str], threshold: float = COMPLETENESS_THRESHOLD
) -> dict[str, Any]:
    """統合本文に元ページの主張が残っているかを機械チェックする（欠落の監視）。

    各元ページの非空行のうち、統合本文に（正規化した上で）出現する割合を測り、
    threshold 未満なら欠落の疑いとして警告する。ハードなゲートではなく HITL の
    補助シグナル（最終確認は人）。

    Returns:
        {"ok": bool, "coverage": 最小カバレッジ, "warnings": [ページ index と割合]}。
    """
    norm_merged = _norm(merged_content)
    warnings: list[str] = []
    worst = 1.0
    for idx, content in enumerate(member_contents):
        lines = [_norm(ln) for ln in (content or "").splitlines() if _norm(ln)]
        if not lines:
            continue
        # frontmatter 区切りや見出し記号だけの行はノイズなので除く
        signif = [ln for ln in lines if len(ln) >= 4 and ln not in ("---",)]
        if not signif:
            continue
        present = sum(1 for ln in signif if _contains(norm_merged, ln))
        coverage = present / len(signif)
        worst = min(worst, coverage)
        if coverage < threshold:
            pct = round(coverage * 100)
            warnings.append(f"ページ{idx + 1}: {pct}% しか統合本文に残っていません")
    return {"ok": not warnings, "coverage": round(worst, 3), "warnings": warnings}


def _contains(haystack_norm: str, line_norm: str) -> bool:
    """正規化済みの行が統合本文に十分含まれるか（完全一致 or 高い部分類似）。"""
    if line_norm in haystack_norm:
        return True
    # 言い換え・語順変化に耐えるため、最も近い部分列との比を見る
    ratio = difflib.SequenceMatcher(None, line_norm, haystack_norm).ratio()
    # 長い haystack との ratio は小さく出るので、行が含まれる度合いを近傍で測る
    return ratio >= 0.6 or _best_window_ratio(haystack_norm, line_norm) >= 0.8


def _best_window_ratio(haystack: str, needle: str) -> float:
    """haystack 内で needle に最も近い同長ウィンドウとの類似度（軽量近似）。"""
    n = len(needle)
    if n == 0 or len(haystack) < n:
        return 0.0
    best = 0.0
    step = max(1, n // 4)
    for start in range(0, len(haystack) - n + 1, step):
        r = difflib.SequenceMatcher(None, needle, haystack[start : start + n]).ratio()
        if r > best:
            best = r
            if best >= 0.95:
                break
    return best


def main(
    query: str,
    proposals: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Dify Code ノード用エントリ（承認 → 統合ジョブ組み立て）。

    Args:
        query: ユーザーの返答（承認か判定する）。
        proposals: 保持していた提案（会話変数から）。
        pages: 承認ターンで再取得した現在の Wiki ページ。

    Returns:
        {"mode": "execute"|"propose", "approved": bool, "jobs": [...], "count": ジョブ数}。
        承認語があり統合対象（高確信クラスタ）があるときだけ mode="execute"。
        それ以外は "propose"（提示のみ）。会話変数を使わず、実行ターンで再検出する
        （検出は決定的なので冪等。統合済みは再検出で候補に挙がらない）。
    """
    approved = is_approval(query)
    jobs: list[dict[str, Any]] = []
    if approved:
        jobs = prepare_merge_jobs(select_executable(proposals or []), pages or [])
    mode = "execute" if (approved and jobs) else "propose"
    return {"mode": mode, "approved": approved, "jobs": jobs, "count": len(jobs)}
