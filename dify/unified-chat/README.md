# unified-chat-router

統一チャット v1 の決定的ルーティングコア。
ユーザー入力（メッセージ + 添付の抽出テキスト）を qa / register / bulk に振り分ける。

- 設計: [docs/unified-chat-design.md](../../docs/unified-chat-design.md)
- `router/routing.py` の `main()` をそのまま Dify の Code ノードに貼り付けられる
  （標準ライブラリのみ・決定的）。
- 統合版 Chatflow DSL は `dify/workflows/unified-chat-bot.yml`。
  **直接編集せず**、元 DSL（質問/登録/一括の 3 本）とスクリプトを直して再生成する:

```bash
cd dify/unified-chat
uv run pytest -q                                  # ルーターの単体テスト
uv run --with pyyaml python tools/build_dsl.py    # DSL を再生成
```
