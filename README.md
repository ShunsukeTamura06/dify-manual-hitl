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
- **特定ベンダー非依存**: Wiki も LLM も差し替え可能。`Wiki + Dify + LLM API キー`
  さえあれば任意の組織で動く（→ [DEPLOYMENT.md](DEPLOYMENT.md)）

詳細は [docs/architecture.md](docs/architecture.md) を参照。
デプロイは [DEPLOYMENT.md](DEPLOYMENT.md)、設定項目は [docs/configuration.md](docs/configuration.md)。

そして全体を貫く設計思想は [docs/design-principles.md](docs/design-principles.md)。
**新しいコンポーネントを追加するときは必ずチェックリストを通すこと。**

## フェーズ

| Phase | 内容 | 状態 |
|-------|------|------|
| 1a | 質問 Bot（RAG・出典・矛盾検出・更新日表示・古さ注記） | 🟢 実機検証済 |
| 1b | Wiki → Dify Knowledge の自動同期（定期 cron + GROWI webhook） | 🟢 実機検証済 |
| 1c | 登録 Bot（アップロード → 整形 → GROWI 下書き、既存とのマージ更新） | 🟢 実機検証済 |
| 1d | 完全 bot（質問/登録/一括取り込み/重複排除/承認待ち確認を 1 チャットに統合） | 🟢 実機検証済 |
| 1e | 重複排除（提示 → 承認 → 統合 → 退役、完全性チェック） | 🟢 実機検証済 |
| 2  | Vision LLM での画像/図形対応、Excel/Word セル結合の展開 | ⚪ 検証のみ・未実装（PoC 済み） |
| 3  | 他チームへの展開（Filesystem/Obsidian Adapter 等の追加） | ⚪ 未着手 |

**Dify + GROWI での一通りの機能を実機で実証済み**
（ローカル: GROWI 7.4.2 + Dify 1.9.2 + OpenAI）。完全 bot への登録（ファイル→整形→
GROWI 下書き）→ GROWI で公開（HITL）→ 自動同期 → 質問（出典 URL・最終更新日つき回答、
異なるマニュアル間の**矛盾を自動検出**）→ 大きなファイルの自動分割登録 → 重複ページの
検出・統合（欠落チェック付き）→ 承認待ち一覧の確認、まで一気通貫で動作確認した。
検証手順は [local-dev/README.md](local-dev/README.md)、デプロイ手順は
[DEPLOYMENT.md](DEPLOYMENT.md)。

詳細は [docs/phase-plan.md](docs/phase-plan.md)、完全 bot の設計は
[docs/unified-chat-design.md](docs/unified-chat-design.md)。

## ディレクトリ

```
.
├── README.md                  # このファイル
├── docs/                      # 設計ドキュメント
│   ├── architecture.md        # アーキテクチャ全体像
│   ├── design-principles.md   # 設計原則（疎結合・交換可能）
│   ├── phase-plan.md          # フェーズ計画
│   └── research-notes.md      # ベストプラクティス調査メモ
├── local-dev/                 # この PC でフルスタック（Dify+GROWI+services）を動かす
│   ├── README.md              # 起動手順・ネットワーク・バージョン方針
│   └── docker-compose.growi.yml # ローカル GROWI（ES なしで軽量）
├── contracts/                 # コンポーネント間の契約（OpenAPI 等）
│   └── docstore-openapi.yaml  # DocStore Adapter API 仕様
├── services/                  # Dify とは独立した HTTP サービス群
│   ├── docstore-growi/        # GROWI 向け DocStore Adapter（pending-approval/deprecate 含む）
│   └── sync/                  # DocStore → Dify Knowledge 同期サービス（webhook + cron 自動化）
├── dify/
│   ├── workflows/             # Dify Chatflow/Workflow DSL（インポート成果物）
│   │   ├── unified-chat-bot.yml         # 完全 bot（推奨・これ1本をインポート）
│   │   ├── phase1a-qa-bot.yml           # 質問 Bot（完全bot の構成部品ソース）
│   │   ├── phase1c-registration-bot.yml # 登録 Bot（同上）
│   │   ├── bulk-import-bot.yml          # 一括取り込み Bot（同上）
│   │   ├── dedup-bot.yml                # 重複排除 Bot（同上。単体インポートも可）
│   │   ├── phase1c-setup.md             # 登録 Bot の UI 構築手順 + 一気通貫テスト
│   │   ├── prompts/                     # 整形プロンプト
│   │   └── README.md                    # インポート手順
│   ├── unified-chat/          # 完全 bot のルーターコア（Python・テスト付き）+ DSL 合成スクリプト
│   └── dedup/                 # 重複排除のクラスタリング/統合ロジック（Python・テスト付き）+ DSL 合成スクリプト
├── conventions/               # IA・ライティング規約・テンプレ
│   ├── manual-template.md     # 標準マニュアルテンプレート
│   └── writing-style.md       # ライティング規約（RAG 最適化）
└── evaluation/                # 実データ評価パック（Phase 1a ゲート。会社端末で1回で実行）
    ├── README.md              # 会社端末での実行手順（runbook）
    ├── import_apps.py         # Bot DSL を環境値でパッチして一括インポート（stdlib のみ）
    └── run_eval.py            # 20問評価 → 採点表を出力（stdlib のみ）
```

**重要**: `services/` と `contracts/` は Dify 非依存。
Dify は HTTP Request ノードで services を叩くだけで、内部実装を知らない。

## 今やること

Dify + GROWI での機能一式（Phase 1a〜1e）は完成・実機検証済み。
新規に環境を用意する場合は [DEPLOYMENT.md](DEPLOYMENT.md) の手順に従う
（`unified-chat-bot.yml` を 1 つインポートすれば動く）。

次の意思決定ポイントは Phase 2（Vision LLM 前処理、Excel/Word のセル結合展開）と
Phase 3（GROWI 以外の Wiki への展開）。どちらも PoC 止まりで、実装は未着手。
実データでの評価（[evaluation/README.md](evaluation/README.md)）を先に回して、
着手の優先度を判断する。
