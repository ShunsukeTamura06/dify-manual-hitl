"""ウィンドウ分割の単体テスト。

検証の柱:
1. 内容欠落なし（98% 脱落バグの再発防止の本丸）。
2. 文書非依存（性質の異なる 5 種類の文書すべてで成立する）。
3. 上限を（ハードスプリット後も）超えない。
"""

import re

import pytest

from splitter.windows import DEFAULT_MAX_CHARS, main, split_into_windows
from tests.fixtures import ALL_DOC_BUILDERS, single_giant_paragraph


def _no_ws(s: str) -> str:
    """空白をすべて除いた文字列（内容欠落の比較用）。"""
    return re.sub(r"\s+", "", s)


@pytest.mark.parametrize("name", list(ALL_DOC_BUILDERS))
def test_no_content_loss_across_doc_types(name: str) -> None:
    """どの文書種類でも、連結すれば非空白文字が完全に保存される。"""
    text = ALL_DOC_BUILDERS[name]()
    windows = split_into_windows(text, max_chars=2000)
    assert _no_ws("".join(windows)) == _no_ws(text)


@pytest.mark.parametrize("name", list(ALL_DOC_BUILDERS))
def test_windows_respect_max_after_hard_split(name: str) -> None:
    """全ウィンドウが上限以下（ハードスプリットも上限を守る）。"""
    max_chars = 2000
    windows = split_into_windows(ALL_DOC_BUILDERS[name](), max_chars=max_chars)
    assert windows  # 空にはならない
    assert all(len(w) <= max_chars for w in windows)


@pytest.mark.parametrize("name", list(ALL_DOC_BUILDERS))
def test_actually_splits_large_docs(name: str) -> None:
    """大きな文書は 1 ウィンドウに集約されず、複数に分かれる（圧縮バグの逆）。"""
    windows = split_into_windows(ALL_DOC_BUILDERS[name](), max_chars=2000)
    assert len(windows) > 1


def test_empty_input_returns_empty() -> None:
    assert split_into_windows("") == []
    assert split_into_windows("   \n\n  \t ") == []


def test_small_input_is_single_window() -> None:
    text = "短いマニュアル。\n\nこれは1ウィンドウに収まる。"
    windows = split_into_windows(text, max_chars=DEFAULT_MAX_CHARS)
    assert len(windows) == 1
    assert _no_ws(windows[0]) == _no_ws(text)


def test_paragraph_boundaries_are_preserved() -> None:
    """上限内なら段落を途中で割らない（先頭・末尾が段落境界に一致）。"""
    paras = [f"段落{n}の本文。" * 20 for n in range(10)]
    text = "\n\n".join(paras)
    windows = split_into_windows(text, max_chars=600)
    # 各ウィンドウは段落単位の連結なので、元のどれかの段落で始まる。
    for w in windows:
        assert any(w.startswith(p) for p in paras)


def test_single_giant_paragraph_is_hard_split() -> None:
    """改行なしの巨大段落でも、上限以下のピースに分割され内容を保つ。"""
    text = single_giant_paragraph(30000)
    windows = split_into_windows(text, max_chars=2000)
    assert len(windows) >= 15
    assert all(len(w) <= 2000 for w in windows)
    assert "".join(windows) == text  # 1 段落・空白なしなので完全一致


def test_long_line_within_paragraph_is_char_split() -> None:
    """段落内の 1 行が上限超過でも文字位置で割れる（表の長い行など）。"""
    long_line = "列|" * 1500  # 1 行で 3000 字、改行なし
    text = f"見出し\n\n{long_line}"
    windows = split_into_windows(text, max_chars=1000)
    assert all(len(w) <= 1000 for w in windows)
    assert _no_ws("".join(windows)) == _no_ws(text)


def test_main_wrapper_shape() -> None:
    """Dify Code ノード入口の戻り値形状。"""
    out = main("段落A。\n\n段落B。")
    assert set(out) == {"windows"}
    assert isinstance(out["windows"], list)
    assert all(isinstance(w, str) for w in out["windows"])


def test_main_accepts_array_file_input() -> None:
    """is_array_file の Document Extractor は text を array[string] で返す。"""
    out = main(["ファイル1の本文。", "ファイル2の本文。"])
    assert out["windows"] == ["ファイル1の本文。\n\nファイル2の本文。"]


def test_main_handles_none() -> None:
    assert main(None) == {"windows": []}
