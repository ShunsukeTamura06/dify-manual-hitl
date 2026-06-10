# manual-knowledge-system

社内マニュアルを LLM で「整備・一元化・質問応答」できるようにする仕組み。
Dify を中核に、Wiki 層（GROWI 等）と疎結合に組み合わせて構築する。

## ゴール

- マニュアルのアップロードを起点に、LLM が**整形 → 一元化環境に登録**するパイプラインを作る
- 一元化環境は**人も LLM も読める**。Wiki が Single Source of Truth
- 登録時は **HITL（人間確認）** を経由する
- ユーザーは LLM に**自然言語で質問**でき、出典付きで正確な回答が返る

## 設計の要点

- **LLM Wiki パターン**（Karpathy）を採用: Wiki が真実の保持者、Dify Knowledge は派生インデックス
- **Wiki 層は差し替え可能**: 現チームは GROWI、他チームには Git+Markdown 等を提供
- **IA は Diátaxis 4 分類**（Tutorial / How-to / Reference / Explanation）
- **検索は Hybrid + Rerank + Parent-Child Chunking**（2026 production standard）

詳細は [docs/architecture.md](docs/architecture.md) を参照。

そして全体を貫く設計思想は [docs/design-principles.md](docs/design-principles.md)。
**新しいコンポーネントを追加するときは必ずチェックリストを通すこと。**

## フェーズ

| Phase | 内容 | 状態 |
|-------|------|------|
| 1a | 質問 Bot 単体で RAG 品質を検証（手動でマニュアル投入） | 🟢 進行中 |
| 1b | Wiki → Dify Knowledge の自動同期 | ⚪ 未着手 |
| 1c | 登録 Bot（アップロード → 整形 → ドラフト → HITL → 登録） | 🟡 実装完了・実機検証待ち |
| 2  | Vision LLM での画像/図形対応、前処理サービス | ⚪ 未着手 |
| 3  | 他チームへの展開（Adapter 差し替え） | ⚪ 未着手 |

詳細は [docs/phase-plan.md](docs/phase-plan.md)。

## ディレクトリ

```
.
├── README.md                  # このファイル
├── docs/                      # 設計ドキュメント
│   ├── architecture.md        # アーキテクチャ全体像
│   ├── design-principles.md   # 設計原則（疎結合・交換可能）
│   ├── phase-plan.md          # フェーズ計画
│   └── research-notes.md      # ベストプラクティス調査メモ
├── contracts/                 # コンポーネント間の契約（OpenAPI 等）
│   └── docstore-openapi.yaml  # DocStore Adapter API 仕様
├── services/                  # Dify とは独立した HTTP サービス群
│   ├── docstore-growi/        # GROWI 向け DocStore Adapter
│   └── sync/                  # DocStore → Dify Knowledge 同期サービス
├── dify/
│   └── workflows/             # Dify Chatflow/Workflow DSL
│       ├── phase1a-qa-bot.yml          # 質問 Bot
│       ├── phase1c-registration-bot.yml # 登録 Bot（参照用 YAML）
│       ├── phase1c-setup.md            # 登録 Bot の UI 構築手順 + 一気通貫テスト
│       ├── prompts/                    # 登録 Bot のプロンプト（整形）
│       └── README.md                   # インポート手順
└── conventions/               # IA・ライティング規約・テンプレ
    ├── manual-template.md     # 標準マニュアルテンプレート
    └── writing-style.md       # ライティング規約（RAG 最適化）
```

**重要**: `services/` と `contracts/` は Dify 非依存。
Dify は HTTP Request ノードで services を叩くだけで、内部実装を知らない。

## 今やること（Phase 1a）

1. `dify/workflows/README.md` の手順に従って、Dify にナレッジを作成
2. 既存マニュアル 5-10 本をアップロード
3. `phase1a-qa-bot.yml` をインポートしてキー類を差し替え
4. 実地で 20 件の質問テスト
5. 評価ルーブリックで合否判定 → 次フェーズの意思決定
