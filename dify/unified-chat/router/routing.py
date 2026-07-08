"""統一チャット（完全 bot）: 決定的サニタイズ付きルーティング。

qa / register / bulk / dedup の 4 機能を 1 入口で振り分ける。ユーザーはどの機能かを
選ばず、bot が意図を汲んで自律的にルートを決める。設計は
[docs/unified-chat-design.md] を参照。

方針:
- **添付の有無・抽出文字数・明示キーワードは決定的に判定**する（書込系フローの
  誤発火を防ぐ。ここを LLM に委ねると、質問のつもりが書き込まれる等の事故が起きる）。
- **意図が曖昧な部分（質問か重複整理の依頼か等）は LLM の分類結果（llm_intent）を
  採用**する＝自律的。ただし LLM の結果は必ず「添付という物理的事実」で矯正する
  （添付が無いのに書込系を選ぶ、を許さない）。

ルート:
- qa       : 質問応答（RAG）
- register : 1 ファイル → 1 ページ登録／既存ページへのマージ更新
- bulk     : 大きな文書を複数ページに分割取り込み
- dedup    : Wiki の重複ページを検出して統合を提案（提示まで）

このファイルは標準ライブラリのみで完結しており、`main` をそのまま Dify の
Code ノードに貼り付けられる。
"""

# bulk（分割取り込み）に切り替える抽出テキスト長の閾値（スプリッターのウィンドウ上限）。
BULK_THRESHOLD_CHARS = 7000

# 決定的に優先する明示キーワード（正規表現・LLM は使わない）
_BULK_KEYWORDS = ("分割", "一括")
_REGISTER_KEYWORDS = ("更新",)
_DEDUP_KEYWORDS = ("重複", "重複排除")

ROUTE_QA = "qa"
ROUTE_REGISTER = "register"
ROUTE_BULK = "bulk"
ROUTE_DEDUP = "dedup"
_VALID_ROUTES = (ROUTE_QA, ROUTE_REGISTER, ROUTE_BULK, ROUTE_DEDUP)


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


def _clean_intent(llm_intent: object) -> str:
    """ルーター LLM の出力からルート名を取り出す（前後の語や記号を許容）。

    LLM は "bulk" のように 1 語で返す想定だが、"route: dedup" や全角・引用符混じりでも
    拾えるよう部分一致で正規化する。未知の出力は空文字（＝LLM 判断なし扱い）。
    """
    s = str(llm_intent or "").strip().lower()
    for route in _VALID_ROUTES:
        if route in s:
            return route
    return ""


def decide_route(
    query: str,
    extracted_text: object,
    llm_intent: object = None,
    threshold: int = BULK_THRESHOLD_CHARS,
) -> str:
    """メッセージ・添付・LLM 意図から最終ルートを決める（決定的サニタイズ）。

    Args:
        query: ユーザーのメッセージ（sys.query）。
        extracted_text: Document Extractor の出力（str / list[str] / None）。
            添付が無い場合は空になる。
        llm_intent: ルーター LLM が分類した意図（qa/register/bulk/dedup）。無くてもよい。
        threshold: bulk に切り替える抽出テキスト長。

    Returns:
        "qa" / "register" / "bulk" / "dedup" のいずれか。
    """
    text = _coerce_text(extracted_text)
    q = query or ""
    intent = _clean_intent(llm_intent)
    has_attachment = bool(text.strip())

    if not has_attachment:
        # 添付なし＝書込材料が無い。register/bulk は物理的にあり得ないので、
        # LLM が書込系を提案しても qa/dedup に矯正する（誤発火の遮断）。
        if intent == ROUTE_DEDUP or any(k in q for k in _DEDUP_KEYWORDS):
            return ROUTE_DEDUP
        return ROUTE_QA

    # 添付あり＝書込系。誤ると影響が大きいので、確実に判定できる材料を優先する。
    if any(k in q for k in _BULK_KEYWORDS):
        return ROUTE_BULK
    if any(k in q for k in _REGISTER_KEYWORDS):
        return ROUTE_REGISTER
    if len(text) > threshold:
        return ROUTE_BULK
    # 決定打が無ければ LLM の bulk 提案だけ尊重（分割は取り逃すと欠落する）。
    # dedup/qa は添付ありでは選べない（書込対象があるため register に倒す）。
    if intent == ROUTE_BULK:
        return ROUTE_BULK
    return ROUTE_REGISTER


def main(query: str, extracted_text: object = None, llm_intent: object = None) -> dict[str, str]:
    """Dify Code ノード用エントリ。

    Args:
        query: sys.query。
        extracted_text: Document Extractor の出力（添付なしなら空/None）。
        llm_intent: ルーター LLM の分類結果（無くてもよい）。

    Returns:
        {"route": "qa"|"register"|"bulk"|"dedup"}。後続の IF/ELSE で分岐する。
    """
    return {"route": decide_route(query, extracted_text, llm_intent)}
