"""重複排除コアの単体テスト。

検証の柱:
1. 候補ペアから正しくクラスタ化（推移閉包・閾値・サイズ2以上のみ）。
2. 確信度の振り分け（高確信=一括 / 曖昧=個別）が意図どおり。
3. 提案の組み立て（基準ページ＝最長 content、順序安定）。
4. 文書非依存（特定マーカーに依存しない）。
"""

from dedup.clustering import (
    build_proposals,
    classify_confidence,
    cluster_min_overlap,
    main,
    overlap_ratio,
)


def _page(pid: str, title: str, content: str, path: str = "") -> dict:
    return {"id": pid, "title": title, "content": content, "path": path or f"/manuals/{title}"}


def test_overlap_ratio_identical_and_disjoint() -> None:
    assert overlap_ratio("まったく同じ本文です。", "まったく同じ本文です。") == 1.0
    assert overlap_ratio("りんご", "コンピュータ設定手順") < 0.3


def test_cluster_min_overlap_uses_worst_pair() -> None:
    # 1つだけ大きく外れたメンバーがあれば凝集度は低くなる
    texts = ["共通の本文 A", "共通の本文 A だいたい同じ", "全然違う無関係な内容ZZZ"]
    assert cluster_min_overlap(texts) < 0.5


def test_transitive_clustering() -> None:
    # a-b, b-c のペアから {a,b,c} の1クラスタ
    pages = [_page("a", "T", "x"), _page("b", "T", "x"), _page("c", "T", "x"), _page("d", "U", "y")]
    pairs = [("a", "b", 0.9), ("b", "c", 0.9)]
    props = build_proposals(pages, pairs)
    assert len(props) == 1
    assert set(props[0]["page_ids"]) == {"a", "b", "c"}


def test_threshold_excludes_weak_pairs() -> None:
    pages = [_page("a", "T", "x"), _page("b", "T", "x")]
    # min_score を上げると弱いペアは連結されずクラスタ無し
    assert build_proposals(pages, [("a", "b", 0.5)], min_score=0.8) == []
    assert len(build_proposals(pages, [("a", "b", 0.9)], min_score=0.8)) == 1


def test_singletons_are_not_proposed() -> None:
    pages = [_page("a", "T", "x"), _page("b", "U", "y")]
    assert build_proposals(pages, []) == []


def test_high_confidence_when_overlap_high_and_titles_agree() -> None:
    body = "宿泊費の精算手順。金額と宿泊数を入力し、領収書を添付して申請する。" * 3
    pages = [
        _page("p1", "宿泊費を精算する", body),
        _page("p2", "宿泊費を精算する", body + "（軽微な差分）"),
    ]
    props = build_proposals(pages, [("p1", "p2", 0.95)])
    assert len(props) == 1
    assert props[0]["confidence"] == "high"
    assert props[0]["lane"] == "bulk"


def test_review_when_titles_disagree() -> None:
    body = "宿泊費の精算手順。金額と宿泊数を入力し申請する。" * 3
    pages = [
        _page("p1", "宿泊費を精算する", body),
        _page("p2", "出張宿泊の費用申請について", body),  # 同内容だがタイトル不一致
    ]
    props = build_proposals(pages, [("p1", "p2", 0.95)])
    assert props[0]["confidence"] == "review"
    assert props[0]["lane"] == "individual"


def test_review_when_overlap_low() -> None:
    pages = [
        _page("p1", "経費精算", "交通費の精算手順についての説明。" * 3),
        _page("p2", "経費精算", "全く異なる内容。休暇申請のやり方ZZZ。" * 3),
    ]
    props = build_proposals(pages, [("p1", "p2", 0.9)])  # 検索上は近いがテキストは乖離
    assert props[0]["confidence"] == "review"


def test_classify_confidence_thresholds() -> None:
    assert classify_confidence(0.85, True) == "high"
    assert classify_confidence(0.85, False) == "review"
    assert classify_confidence(0.5, True) == "review"


def test_representative_is_longest_content() -> None:
    pages = [
        _page("short", "宿泊費を精算する", "短い見出しのみ", path="/a"),
        _page("long", "宿泊費を精算する", "詳しい本文。" * 30, path="/b"),
    ]
    props = build_proposals(pages, [("short", "long", 0.9)])
    assert props[0]["representative_path"] == "/b"


def test_clusters_ordered_by_first_appearance() -> None:
    pages = [_page(str(i), "T", "x") for i in range(6)]
    pairs = [("4", "5", 0.9), ("0", "1", 0.9)]
    props = build_proposals(pages, pairs)
    # ページ出現順（0..5）に従い {0,1} のクラスタが先
    assert props[0]["page_ids"] == ["0", "1"]
    assert props[1]["page_ids"] == ["4", "5"]


def test_pairs_accept_dict_form() -> None:
    pages = [_page("a", "T", "x"), _page("b", "T", "x")]
    props = build_proposals(pages, [{"a": "a", "b": "b", "score": 0.9}])
    assert len(props) == 1


def test_main_wrapper_shape() -> None:
    pages = [_page("a", "T", "x"), _page("b", "T", "x")]
    out = main(pages, [("a", "b", 0.9)])
    assert set(out) == {"proposals"}
    assert isinstance(out["proposals"], list)


def test_main_handles_empty() -> None:
    assert main([], []) == {"proposals": []}
