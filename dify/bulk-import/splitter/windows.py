"""一括取り込み Bot: ウィンドウ分割（Dify Code ノード / ローカル単体テスト共用）。

巨大な抽出テキストを、段落境界で ~6-8K 字のウィンドウに機械分割する。
Map-Reduce（案A）の Map 前段。

最重要の制約（docs/splitter-design.md「汎用性の制約」）:
- 文書構造に一切依存しない。見出し正規表現・「事例N」「第N章」等のドメイン特定
  マーカーをハードコードしない。
- 分割は段落境界（空行）→ 行 → 文字 の機械的フォールバックのみで行う。
  「適切な単位」の意味判断は後段の LLM に委ねる。

このファイルは標準ライブラリのみで完結しており、`main` をそのまま Dify の
Code ノードに貼り付けられる。ローカルでは `split_into_windows` を単体テストする。
"""

import re

# 1 ウィンドウの目標上限（文字数）。段落単位で詰めるため実際の長さは前後する。
# LLM の入力文脈上限ではなく「1 回の出力に無理なく収まる入力量」を意図した値。
DEFAULT_MAX_CHARS = 7000

_PARAGRAPH_SEP = re.compile(r"\n[ \t]*\n")


def _split_paragraphs(text: str) -> list[str]:
    """空行で段落に分ける。中身が空白だけの段落は捨てる。"""
    return [p for p in _PARAGRAPH_SEP.split(text) if p.strip()]


def _hard_split(chunk: str, max_chars: int) -> list[str]:
    """上限を超える 1 段落を、行 → 文字 の順で機械分割する。

    表の 1 行が極端に長い等のケースでも内容を落とさないためのフォールバック。

    Args:
        chunk: 上限を超えうる単一段落。
        max_chars: 1 ピースの上限文字数。

    Returns:
        分割後のピース列（連結すると元の chunk に一致する）。
    """
    if len(chunk) <= max_chars:
        return [chunk]
    pieces: list[str] = []
    buf = ""
    for line in chunk.splitlines(keepends=True):
        # 1 行自体が上限を超える場合は文字位置で割る。
        while len(line) > max_chars:
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(line[:max_chars])
            line = line[max_chars:]
        if buf and len(buf) + len(line) > max_chars:
            pieces.append(buf)
            buf = ""
        buf += line
    if buf:
        pieces.append(buf)
    return pieces


def split_into_windows(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """テキストを段落境界で ~max_chars 字のウィンドウに分割する。

    段落（空行区切り）を順に詰め、上限を超える直前でウィンドウを確定する。
    単一段落が上限を超える場合のみ `_hard_split` で機械分割する。
    内容は欠落させない（連結すると元テキストの非空白文字をすべて含む）。

    Args:
        text: 抽出済みの全文テキスト。
        max_chars: 1 ウィンドウの目標上限文字数。

    Returns:
        ウィンドウ文字列のリスト（元の順序を保持）。
    """
    windows: list[str] = []
    buf = ""
    for para in _split_paragraphs(text):
        if len(para) > max_chars:
            # 現在のバッファを確定してから巨大段落を機械分割する。
            if buf:
                windows.append(buf)
                buf = ""
            windows.extend(_hard_split(para, max_chars))
            continue
        candidate = para if not buf else f"{buf}\n\n{para}"
        if len(candidate) > max_chars:
            windows.append(buf)
            buf = para
        else:
            buf = candidate
    if buf:
        windows.append(buf)
    return windows


def _coerce_text(text: object) -> str:
    """Document Extractor の出力を文字列に正規化する。

    複数ファイル対応（is_array_file）の抽出ノードは text を array[string] で返すため、
    リストで来たら段落区切りで連結する。None は空文字にする。
    """
    if isinstance(text, list):
        return "\n\n".join(str(t) for t in text if t)
    if text is None:
        return ""
    return str(text)


def main(text: object) -> dict[str, list[str]]:
    """Dify Code ノード用エントリ。

    Args:
        text: 前段（Document Extractor / 前処理）から渡る抽出テキスト。
            単一文字列でも array[string]（複数ファイル）でも受け付ける。

    Returns:
        {"windows": [ウィンドウ文字列, ...]}。後続の Iteration ノードで反復する。
    """
    return {"windows": split_into_windows(_coerce_text(text), DEFAULT_MAX_CHARS)}
