# unified-chat-router

統一チャット v1 の決定的ルーティングコア。
ユーザー入力（メッセージ + 添付の抽出テキスト）を qa / register / bulk に振り分ける。

- 設計: [docs/unified-chat-design.md](../../docs/unified-chat-design.md)
- `router/routing.py` の `main()` をそのまま Dify の Code ノードに貼り付けられる
  （標準ライブラリのみ・決定的）。
- 統合版 Chatflow DSL は `dify/workflows/unified-chat-bot.yml`。

```bash
cd dify/unified-chat
uv run pytest -q
```
