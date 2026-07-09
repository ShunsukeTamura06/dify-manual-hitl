"""重複排除 実行フェーズ（承認→統合ジョブ組み立て→完全性）の単体テスト。"""

from dedup.clustering import build_proposals_from_content
from dedup.execution import (
    check_completeness,
    is_approval,
    main,
    prepare_merge_jobs,
    select_executable,
)


def _page(pid: str, title: str, content: str, path: str = "") -> dict:
    return {"id": pid, "title": title, "content": content, "path": path or f"/m/{title}"}


# ── 承認判定 ──


def test_is_approval_positive() -> None:
    for q in ["承認", "統合してください", "実行して", "まとめてOK", "はい"]:
        assert is_approval(q) is True


def test_is_approval_negative() -> None:
    # 曖昧・質問・修正指示は承認扱いにしない（勝手に実行しない）
    for q in ["", "これ何？", "やめて", "もう少し詳しく", "経費精算の上限は？"]:
        assert is_approval(q) is False


# ── 実行対象の選別（高確信のみ）──


def test_select_executable_only_bulk() -> None:
    proposals = [
        {"cluster_id": 1, "lane": "bulk"},
        {"cluster_id": 2, "lane": "individual"},
    ]
    got = select_executable(proposals)
    assert [p["cluster_id"] for p in got] == [1]


# ── 統合ジョブの組み立て ──


def _sample_cluster_pages() -> list[dict]:
    body = "宿泊費の精算手順。金額と宿泊数を入力し領収書を添付して申請する。" * 3
    return [
        _page("p1", "宿泊費を精算する", body + "\n追加の注記あり", path="/m/経理/宿泊費"),
        _page("p2", "宿泊費精算", body),
        _page("p3", "宿泊費の申請", body),
    ]


def test_prepare_merge_jobs_basic() -> None:
    pages = _sample_cluster_pages()
    proposals = select_executable(build_proposals_from_content(pages))
    jobs = prepare_merge_jobs(proposals, pages)
    assert len(jobs) == 1
    job = jobs[0]
    # 基準ページ = 最長 content（p1、追記あり）
    assert job["representative_id"] == "p1"
    assert job["representative_path"] == "/m/経理/宿泊費"
    # 退役対象は基準以外
    assert set(job["deprecated_ids"]) == {"p2", "p3"}
    # 統合入力に全メンバーの本文が含まれる
    assert "宿泊費を精算する" in job["merge_input"]
    assert len(job["member_contents"]) == 3


def test_prepare_merge_jobs_skips_vanished_cluster() -> None:
    # ページが消えて単独化したクラスタは統合しない（冪等・安全）
    proposals = [
        {
            "page_ids": ["p1", "p2"],
            "representative_id": "p1",
            "representative_path": "/m/x",
            "lane": "bulk",
        }
    ]
    pages = [_page("p1", "残り", "本文")]  # p2 が消えた
    assert prepare_merge_jobs(proposals, pages) == []


def test_prepare_merge_jobs_reselects_rep_if_missing() -> None:
    # 基準ページが消えていれば残りから最長を選び直す
    proposals = [
        {
            "page_ids": ["p1", "p2", "p3"],
            "representative_id": "p1",
            "representative_path": "/m/old",
            "lane": "bulk",
        }
    ]
    pages = [_page("p2", "B", "短い"), _page("p3", "C", "とても長い本文" * 5)]
    jobs = prepare_merge_jobs(proposals, pages)
    assert len(jobs) == 1
    assert jobs[0]["representative_id"] == "p3"  # 最長
    assert set(jobs[0]["deprecated_ids"]) == {"p2"}


# ── 完全性チェック ──


def test_completeness_ok_when_facts_present() -> None:
    members = [
        "国内出張の交通費を精算する。\n経路と金額を入力する。\n領収書を添付する。",
        "領収書を添付する。\n上長の承認を得る。",
    ]
    merged = (
        "国内出張の交通費を精算する。\n経路と金額を入力する。\n"
        "領収書を添付する。\n上長の承認を得る。"
    )
    result = check_completeness(merged, members)
    assert result["ok"] is True
    assert not result["warnings"]


def test_completeness_flags_dropped_facts() -> None:
    members = [
        "重要な注意: 30日前から予約可能。\n大会議室は部長承認が必要。\n"
        "キャンセルは2時間前まで。\n連続3時間超は事前相談。",
    ]
    merged = "会議室を予約する。手順のみ記載。"  # 注意事項が全部落ちた
    result = check_completeness(merged, members)
    assert result["ok"] is False
    assert result["warnings"]
    assert result["coverage"] < 0.7


# ── main ラッパー ──


def test_main_not_approved_is_propose() -> None:
    pages = _sample_cluster_pages()
    proposals = build_proposals_from_content(pages)
    out = main("これ何？", proposals, pages)
    assert out["mode"] == "propose"
    assert out["approved"] is False
    assert out["jobs"] == []


def test_main_approved_builds_jobs_execute() -> None:
    pages = _sample_cluster_pages()
    proposals = build_proposals_from_content(pages)
    out = main("統合して実行", proposals, pages)
    assert out["mode"] == "execute"
    assert out["approved"] is True
    assert out["count"] == 1
    assert out["jobs"][0]["representative_id"] == "p1"


def test_main_approved_but_no_jobs_is_propose() -> None:
    # 承認語はあるが統合対象（高確信クラスタ）が無ければ propose に倒す
    out = main("承認", [], [])
    assert out["mode"] == "propose"
    assert out["approved"] is True
    assert out["count"] == 0
