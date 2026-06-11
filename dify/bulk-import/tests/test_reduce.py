"""継ぎ合わせ（Reduce）の単体テスト。

検証の柱:
1. ウィンドウ跨ぎのセクションが 1 ページに正しく結合される。
2. 内容を取りこぼさない（フラグ不整合でも欠落させない）。
3. 壊れた LLM 出力でも全体を止めない（耐障害性）。
"""

import json

from splitter.reduce import main, merge_window_pages


def _win(*pages: dict) -> str:
    """ウィンドウの LLM 出力（JSON 文字列）を作るヘルパ。"""
    return json.dumps(list(pages), ensure_ascii=False)


def _page(title: str, content: str, *, cont: bool = False, inc: bool = False) -> dict:
    return {"title": title, "content": content, "continues_previous": cont, "incomplete": inc}


def test_independent_pages_pass_through_in_order() -> None:
    results = [
        _win(_page("はじめに", "概要です。")),
        _win(_page("手順", "操作します。"), _page("FAQ", "質問集です。")),
    ]
    pages = merge_window_pages(results)
    assert [p["title"] for p in pages] == ["はじめに", "手順", "FAQ"]
    assert pages[1]["content"] == "操作します。"


def test_section_split_across_boundary_is_merged() -> None:
    """incomplete ↔ continues_previous で 2 ウィンドウのセクションが 1 つに。"""
    results = [
        _win(_page("長い手順", "前半の内容。", inc=True)),
        _win(_page("", "後半の内容。", cont=True), _page("次の章", "別の話題。")),
    ]
    pages = merge_window_pages(results)
    assert len(pages) == 2
    assert pages[0]["title"] == "長い手順"
    assert "前半の内容。" in pages[0]["content"]
    assert "後半の内容。" in pages[0]["content"]
    assert pages[1]["title"] == "次の章"


def test_section_spanning_three_windows() -> None:
    """中間ウィンドウが両フラグ持ちのセクション（3 ウィンドウ跨ぎ）。"""
    results = [
        _win(_page("超長文", "第1部。", inc=True)),
        _win(_page("", "第2部。", cont=True, inc=True)),
        _win(_page("", "第3部。", cont=True)),
    ]
    pages = merge_window_pages(results)
    assert len(pages) == 1
    assert pages[0]["title"] == "超長文"
    for part in ("第1部。", "第2部。", "第3部。"):
        assert part in pages[0]["content"]


def test_dangling_incomplete_merges_even_if_next_flag_missing() -> None:
    """前ウィンドウ末尾が incomplete なら、次先頭の continues_previous 欠落でも結合（欠落防止）。"""
    results = [
        _win(_page("章", "前半。", inc=True)),
        _win(_page("章の続き", "後半。")),  # continues_previous を立て忘れ
    ]
    pages = merge_window_pages(results)
    assert len(pages) == 1
    assert "前半。" in pages[0]["content"] and "後半。" in pages[0]["content"]


def test_boundary_same_title_merges_without_flags() -> None:
    """実機 gpt-4o-mini 再現: フラグ未設定でも、境界で同名なら結合する。

    見出しのみの stub（ウィンドウ末尾）と本体（次ウィンドウ先頭）が同名で割れても、
    1ページに結合し内容を落とさない（同一パス衝突も防ぐ）。
    """
    results = [
        _win(
            _page("立替金を精算する", "立替金の本文。"),
            _page("定期券を申請する", "定期券を申請する手順を説明します。"),  # stub（見出しのみ）
        ),
        _win(
            _page("定期券を申請する", "1. 区間を選ぶ\n2. 期間を選ぶ\n3. 申請する"),  # 本体
            _page("精算の差戻しに対応する", "差戻しの本文。"),
        ),
    ]
    pages = merge_window_pages(results)
    assert [p["title"] for p in pages] == [
        "立替金を精算する",
        "定期券を申請する",
        "精算の差戻しに対応する",
    ]
    teiki = pages[1]["content"]
    assert "手順を説明します" in teiki
    assert "区間を選ぶ" in teiki and "申請する" in teiki


def test_same_title_not_at_boundary_stays_separate() -> None:
    """同一ウィンドウ内の同名トピックは（境界でないので）結合しない。"""
    results = [_win(_page("注意事項", "A。"), _page("注意事項", "B。"))]
    pages = merge_window_pages(results)
    assert len(pages) == 2


def test_continues_previous_with_no_prior_page_becomes_new() -> None:
    """先頭ウィンドウで continues_previous が立っていても落とさず新規ページにする。"""
    results = [_win(_page("孤児", "中身。", cont=True))]
    pages = merge_window_pages(results)
    assert len(pages) == 1
    assert pages[0]["content"] == "中身。"


def test_broken_and_empty_window_outputs_are_skipped() -> None:
    results = [
        _win(_page("有効", "残る。")),
        "",  # 空
        "これは JSON ではありません",  # 壊れ
        "[",  # 途中切れ
    ]
    pages = merge_window_pages(results)
    assert [p["title"] for p in pages] == ["有効"]


def test_json_wrapped_in_code_fence_is_parsed() -> None:
    fenced = "```json\n" + _win(_page("フェンス", "中身。")) + "\n```"
    pages = merge_window_pages([fenced])
    assert [p["title"] for p in pages] == ["フェンス"]


def test_accepts_pre_parsed_objects() -> None:
    """文字列でなくパース済みの list/dict でも受け付ける。"""
    results = [[_page("配列", "A。")], _page("単体dict", "B。")]
    pages = merge_window_pages(results)
    assert [p["title"] for p in pages] == ["配列", "単体dict"]


def test_main_wrapper_shape() -> None:
    out = main([_win(_page("t", "c"))])
    assert set(out) == {"pages"}
    assert out["pages"] == [{"title": "t", "content": "c"}]
