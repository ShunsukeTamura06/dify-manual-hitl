"""ルーティングコアの単体テスト。

検証の柱:
1. 規則 1〜5 が優先順位どおりに適用される。
2. 境界（ちょうど閾値・空クエリ・複数ファイル・None）で壊れない。
3. 決定的であること（同じ入力は常に同じルート）。
"""

from router.routing import BULK_THRESHOLD_CHARS, decide_route, main


def test_no_attachment_is_qa() -> None:
    # 規則1: 添付なしは質問。書込系キーワードがあっても書込材料が無い
    assert decide_route("経費精算の上限は？", "") == "qa"
    assert decide_route("このファイルを分割して", None) == "qa"
    assert decide_route("更新して", "") == "qa"
    assert decide_route("", "") == "qa"


def test_whitespace_only_extraction_is_qa() -> None:
    # 抽出結果が空白だけ（空ファイル等）も添付なし扱い
    assert decide_route("質問です", "   \n\t  ") == "qa"


def test_small_attachment_is_register() -> None:
    # 規則5: 添付ありの既定は登録
    assert decide_route("お願いします", "小さなマニュアルの本文") == "register"
    assert decide_route("", "本文だけでメッセージなし") == "register"


def test_large_attachment_is_bulk() -> None:
    # 規則4: 閾値超えは一括取り込み
    big = "あ" * (BULK_THRESHOLD_CHARS + 1)
    assert decide_route("取り込んで", big) == "bulk"


def test_threshold_boundary() -> None:
    # ちょうど閾値は register（「超えたら」bulk）
    exactly = "あ" * BULK_THRESHOLD_CHARS
    assert decide_route("お願いします", exactly) == "register"


def test_explicit_bulk_keyword_overrides_size() -> None:
    # 規則2: 小さくても「分割」「一括」の明示指示で bulk
    assert decide_route("この文書を分割して取り込んで", "小さい本文") == "bulk"
    assert decide_route("一括で取り込んでください", "小さい本文") == "bulk"


def test_explicit_update_keyword_is_register() -> None:
    # 規則3: 大きくても「更新」の明示指示で register（マージ経路）
    big = "あ" * (BULK_THRESHOLD_CHARS + 1)
    assert decide_route("「会議室を予約する」を更新して", big) == "register"


def test_bulk_keyword_beats_update_keyword() -> None:
    # 規則2 > 規則3: 「分割」と「更新」が両方あれば bulk
    assert decide_route("分割した上で更新して", "本文") == "bulk"


def test_multiple_files_use_total_length() -> None:
    # 複数ファイル（array[string]）は合計長で判定
    half = "あ" * (BULK_THRESHOLD_CHARS // 2 + 100)
    assert decide_route("お願いします", [half, half]) == "bulk"
    assert decide_route("お願いします", ["小さい", "小さい"]) == "register"


def test_list_with_empty_items() -> None:
    # 空要素・None が混ざっても壊れない
    assert decide_route("質問です", ["", None, ""]) == "qa"


def test_main_wrapper_shape() -> None:
    out = main("経費精算の上限は？", "")
    assert out == {"route": "qa"}
    out = main("お願いします", "本文")
    assert out == {"route": "register"}


def test_deterministic() -> None:
    # 同じ入力は常に同じ結果（決定性）
    args = ("この文書を取り込んで", "あ" * 8000)
    assert len({decide_route(*args) for _ in range(10)}) == 1
