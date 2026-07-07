"""統一チャット v1: 決定的ルーティング（Dify Code ノード / ローカル単体テスト共用）。

ユーザー入力（メッセージ + 添付の抽出テキスト）を qa / register / bulk のいずれかに
振り分ける。v1 は LLM の意図分類を使わず、**確実に判定できる材料だけ**で決める
（誤ルートで書込系フローが誤発火するのを避けるため）。設計は
[docs/unified-chat-design.md] を参照。

規則（優先順位順）:
1. 添付なし → qa（書込材料が無い以上、書込フローはあり得ない）
2. 添付あり + メッセージに「分割」or「一括」 → bulk（明示指示が最優先）
3. 添付あり + メッセージに「更新」 → register（既存ページへのマージ経路）
4. 添付あり + 抽出テキスト > BULK_THRESHOLD_CHARS → bulk（1 回の LLM 出力に
   収まらない量は分割しないと内容が欠落する）
5. 添付あり（上記以外） → register

優先順位の根拠（曖昧な指示の倒し方）:
- 規則 2 > 3（「分割して更新して」は bulk）: 誤って bulk に倒れても新規 draft が
  増えるだけで人が捨てられる。誤って register(更新) に倒れると**既存ページ本文を
  書き換える**（GROWI 履歴で戻せるが影響が大きい）。迷ったら影響の小さい方に倒す。
- 規則 3 > 4（大きい更新素材も register）: bulk は既存ページを更新できない
  （新規作成のみ）ため、「更新」の明示指示を尊重する。巨大な更新素材はマージ LLM の
  出力上限で欠落し得るのは既知の制約（v2 課題。docs/unified-chat-design.md 参照）。

このファイルは標準ライブラリのみで完結しており、`main` をそのまま Dify の
Code ノードに貼り付けられる。
"""

# bulk（分割取り込み）に切り替える抽出テキスト長の閾値。
# 一括取り込みスプリッターのウィンドウ上限（splitter DEFAULT_MAX_CHARS）と同値:
# 「1 回の LLM 出力に無理なく収まる量」を超えたら 1 ページ登録では欠落する。
BULK_THRESHOLD_CHARS = 7000

# 明示指示のキーワード（決定的な部分一致。正規表現・LLM は使わない）
_BULK_KEYWORDS = ("分割", "一括")
_REGISTER_KEYWORDS = ("更新",)

ROUTE_QA = "qa"
ROUTE_REGISTER = "register"
ROUTE_BULK = "bulk"


def _coerce_text(text: object) -> str:
    """Document Extractor の出力を文字列に正規化する。

    複数ファイル対応（is_array_file）の抽出ノードは text を array[string] で返すため、
    リストで来たら連結して合計長で判定する。None は空文字。
    """
    if isinstance(text, list):
        return "\n\n".join(str(t) for t in text if t)
    if text is None:
        return ""
    return str(text)


def decide_route(
    query: str,
    extracted_text: object,
    threshold: int = BULK_THRESHOLD_CHARS,
) -> str:
    """メッセージと抽出テキストからルートを決める（決定的）。

    Args:
        query: ユーザーのメッセージ（sys.query）。
        extracted_text: Document Extractor の出力（str / list[str] / None）。
            添付が無い場合は空になる。
        threshold: bulk に切り替える抽出テキスト長。

    Returns:
        "qa" / "register" / "bulk" のいずれか。
    """
    text = _coerce_text(extracted_text)
    q = query or ""

    if not text.strip():
        return ROUTE_QA
    if any(k in q for k in _BULK_KEYWORDS):
        return ROUTE_BULK
    if any(k in q for k in _REGISTER_KEYWORDS):
        return ROUTE_REGISTER
    if len(text) > threshold:
        return ROUTE_BULK
    return ROUTE_REGISTER


def main(query: str, extracted_text: object = None) -> dict[str, str]:
    """Dify Code ノード用エントリ。

    Args:
        query: sys.query。
        extracted_text: Document Extractor の出力（添付なしなら空/None）。

    Returns:
        {"route": "qa"|"register"|"bulk"}。後続の IF/ELSE ノードで分岐する。
    """
    return {"route": decide_route(query, extracted_text)}
