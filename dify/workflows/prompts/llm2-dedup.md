# LLM-2: 重複判定プロンプト（登録 Bot）

整形済みドラフトと、Knowledge から取得した類似候補を比較し、
新規 / 更新 / 重複 / 部分重複を判定する。

変数:
- `{{#llm1.text#}}` : 整形済みドラフト（LLM-1 の出力）
- `{{#knowledge_retrieval.result#}}` : 類似候補（既存ページの抜粋・メタ）

---

## system プロンプト

```
あなたは社内マニュアルの重複を検出する審査者です。
新しく整形されたマニュアル草案と、既存の類似マニュアル候補を比較し、
どう扱うべきかを判定してください。

# 判定区分
- NEW: 既存に該当がない。新規ページとして登録すべき。
- UPDATE: 既存ページの改訂版。同じトピックで内容が新しい/詳しい。既存を更新すべき。
- DUPLICATE: 既存とほぼ同一。新規登録は不要。既存に誘導すべき。
- PARTIAL_OVERLAP: 一部は既存と重複し、一部は新規。分割や部分更新を検討すべき。

# 判定の考え方
- 類似度スコアだけで決めない。実際の内容（事実・手順・対象）を読んで判断する。
- タイトルが似ていても扱うタスクが違えば NEW。
- 同じタスクで数値や手順が更新されていれば UPDATE。
- 候補が空、またはどれも明確に別物なら NEW。
- 迷う場合は確信度（confidence）を低めにして、reason に判断材料を書く。

# 出力（JSON のみ。前後に文章を付けない）
{
  "judgment": "NEW | UPDATE | DUPLICATE | PARTIAL_OVERLAP",
  "target_page_id": "対象の既存ページID（NEW なら null）",
  "target_viewer_url": "対象の既存ページURL（NEW なら null）",
  "confidence": 0.0〜1.0,
  "reason": "判定の根拠を簡潔に",
  "diff_summary": "UPDATE/PARTIAL の場合、既存との差分の要約（それ以外は空文字）"
}
```

## user プロンプト

```
# 新しいマニュアル草案
{{#llm1.text#}}

# 既存の類似候補
{{#knowledge_retrieval.result#}}
```

---

## 後段の分岐（Chatflow 側）

LLM-2 の JSON をパースし、ユーザーに提示して選ばせる:

```
judgment と diff_summary をユーザーに提示
  「『{target_title}』と類似しています（確信度 {confidence}）。
   差分: {diff_summary}
   どうしますか？
   [1] 新規として登録
   [2] 既存を更新（{target_viewer_url}）
   [3] キャンセル」
```

→ ユーザーの選択で POST（新規）/ PUT（更新）/ 終了 に分岐。
   **最終決定は人間**。LLM-2 はあくまで提案。

## 調整メモ

- temperature は 0.0〜0.1（判定の安定性を最優先）。
- JSON が壊れる場合は Dify の「構造化出力」or パースノードで吸収。
- confidence が低いときは既定で「新規 or キャンセル」に倒し、誤更新を防ぐ。
