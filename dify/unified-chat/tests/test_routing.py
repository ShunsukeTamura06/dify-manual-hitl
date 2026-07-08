"""ルーティングコアの単体テスト（4 ルート・LLM 意図の決定的サニタイズ）。

検証の柱:
1. 添付の有無で書込系（register/bulk）が物理的に遮断される。
2. LLM の意図（llm_intent）は採用されるが、事実（添付）で矯正される。
3. 明示キーワード・サイズは決定的に優先される。
4. 境界・異常入力で壊れない。決定的であること。
"""

from router.routing import BULK_THRESHOLD_CHARS, decide_route, main

# ── 添付なし: qa / dedup のみ（書込系は物理的に不可能）──


def test_no_attachment_default_qa() -> None:
    assert decide_route("経費精算の上限は？", "") == "qa"
    assert decide_route("", None) == "qa"


def test_no_attachment_dedup_by_keyword() -> None:
    # 「重複」の明示で dedup（LLM 判断が無くても拾う）
    assert decide_route("/manuals/経理 の重複を整理して", "") == "dedup"
    assert decide_route("重複排除して", None) == "dedup"


def test_no_attachment_dedup_by_llm_intent() -> None:
    # LLM が意図を dedup と分類したら採用（自律的判断）
    assert decide_route("似たページが多い気がする", "", llm_intent="dedup") == "dedup"


def test_no_attachment_write_intent_is_corrected_to_qa() -> None:
    # 添付が無いのに LLM が register/bulk を出しても qa に矯正（誤発火の遮断）
    assert decide_route("これ登録して", "", llm_intent="register") == "qa"
    assert decide_route("取り込んで", None, llm_intent="bulk") == "qa"


# ── 添付あり: 書込系。決定的優先 + LLM 補助 ──


def test_small_attachment_default_register() -> None:
    assert decide_route("お願いします", "小さな本文") == "register"


def test_large_attachment_is_bulk() -> None:
    big = "あ" * (BULK_THRESHOLD_CHARS + 1)
    assert decide_route("取り込んで", big) == "bulk"


def test_threshold_boundary_is_register() -> None:
    exactly = "あ" * BULK_THRESHOLD_CHARS
    assert decide_route("お願いします", exactly) == "register"


def test_explicit_bulk_keyword_overrides_size() -> None:
    assert decide_route("分割して取り込んで", "小さい本文") == "bulk"


def test_explicit_update_keyword_is_register() -> None:
    big = "あ" * (BULK_THRESHOLD_CHARS + 1)
    assert decide_route("「会議室」を更新して", big) == "register"


def test_llm_bulk_intent_respected_when_no_decisive_signal() -> None:
    # 決定打（キーワード・サイズ）が無いとき、LLM の bulk 提案を尊重
    assert decide_route("これ整理して入れて", "中くらいの本文", llm_intent="bulk") == "bulk"


def test_attachment_with_dedup_intent_corrected_to_register() -> None:
    # 添付があるのに LLM が dedup/qa を出しても、書込対象がある以上 register に倒す
    assert decide_route("お願い", "本文", llm_intent="dedup") == "register"
    assert decide_route("お願い", "本文", llm_intent="qa") == "register"


# ── LLM 出力の正規化・堅牢性 ──


def test_llm_intent_extracted_from_noisy_output() -> None:
    # "route: bulk" のような前後語つきでも拾う
    big = "あ" * 100  # 小さいので決定打なし → intent 依存
    assert decide_route("入れて", big, llm_intent="route: bulk") == "bulk"
    assert decide_route("見て", "", llm_intent='{"intent": "dedup"}') == "dedup"


def test_unknown_llm_intent_ignored() -> None:
    # 未知の intent は無視され、決定的既定に落ちる
    assert decide_route("質問です", "", llm_intent="banana") == "qa"
    assert decide_route("お願い", "本文", llm_intent="") == "register"


def test_multiple_files_use_total_length() -> None:
    half = "あ" * (BULK_THRESHOLD_CHARS // 2 + 100)
    assert decide_route("お願いします", [half, half]) == "bulk"


def test_list_with_empty_items_is_qa() -> None:
    assert decide_route("質問です", ["", None, ""]) == "qa"


def test_main_wrapper_shape() -> None:
    assert main("経費の上限は？", "") == {"route": "qa"}
    assert main("お願い", "本文") == {"route": "register"}
    assert main("重複見て", "", "dedup") == {"route": "dedup"}


def test_deterministic() -> None:
    args = ("これ取り込んで", "あ" * 8000)
    assert len({decide_route(*args) for _ in range(10)}) == 1
