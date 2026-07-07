# フェーズ計画

「動くもの → 痛みの観察 → 改善」のサイクルを回す前提で、小さく切る。

## Phase 1a: RAG 品質の検証 🟢

**目的:** そもそも我々のマニュアル群で RAG が使い物になる品質を出せるかを検証する。
最大のリスク（=RAG 品質）を最小の投資で潰す。

**スコープ:**
- Dify ナレッジを 1 つ作成
- 既存マニュアル 5-10 本を**手動でアップロード**（整形なし）
- 質問 Bot Chatflow を構築
- チームで 20 件の実地質問テスト

**やらないこと:**
- Wiki 同期（自動化なし）
- 登録 Bot（手動アップロードのみ）
- Vision LLM 前処理
- Word/Excel の高度なパース（Dify 標準抽出のみ）

**成果物:**
- [dify/workflows/phase1a-qa-bot.yml](../dify/workflows/phase1a-qa-bot.yml)

**評価ルーブリック:**

> 実行手段: [evaluation/](../evaluation/)（会社端末で 1 回で実行できる評価パック。
> 質問 20 問 → 回答・引用・応答秒を自動収集 → この採点表を出力）。
> **注意: ローカル（トイデータ）での動作確認は済んでいるが、実マニュアル・実質問での
> このゲート判定はまだ実施していない。**

20 件の質問・回答を以下で採点。

| 観点 | 配点 | 判定 |
|------|------|------|
| 正確性 | ◎/○/△/× | 事実として正しいか |
| 完全性 | ◎/○/△/× | 必要情報が揃っているか |
| 出典妥当性 | ◎/○/△/× | 引用元が正しい場所か |
| 「該当なし」判定 | ◎/× | 無いものを無いと言えるか |
| 応答速度 | 秒 | 5秒以内が望ましい |

**意思決定:**
- ◎○ が 70% 以上 → **Phase 1b へ**（同期自動化に投資する価値あり）
- 50-70% → **コンテンツ整備を先に**（IA 規約・ライティング規約を整える）
- 50% 未満 → **アーキテクチャ見直し**（Vision LLM 前処理を Phase 2 から繰り上げ等）

---

## Phase 1b: Wiki → Dify 同期 ⚪

**目的:** Wiki を Single Source of Truth として、Dify Knowledge への自動同期を確立する。

**スコープ:**
- DocStore Adapter インターフェースの確定
- GROWI Adapter の実装
- Wiki → Dify Knowledge 同期スクリプト
  - Webhook（リアルタイム） + 日次バッチ（取りこぼし保険）
- 質問 Bot の引用に Wiki URL を埋め込む

**成果物:**
- `dify/adapters/growi_adapter.py`
- `dify/adapters/sync_service.py`
- 質問 Bot YAML を更新版に

---

## Phase 1c: 登録 Bot ⚪

**目的:** ユーザーがファイルをアップロード → LLM が整形 → Wiki にドラフト作成 → 公開で同期、まで自動化。

**スコープ:**
- 登録 Bot Chatflow
  - ファイル受け取り
  - LLM-1: 標準テンプレートに整形
  - Dify Knowledge で類似検索（重複チェック）
  - LLM-2: 新規/更新/重複を判定
  - Wiki にドラフトページ作成（DocStore Adapter 経由）
  - ユーザーに「Wiki で確認・公開してください」と通知
- HITL は「Wiki 上で編集・公開する」操作で代用

**成果物:**
- `dify/workflows/phase1c-registration-bot.yml`

---

## Phase 2: Vision LLM 対応 ⚪

**目的:** Word/Excel の図形・矢印・SmartArt を Mermaid 化し、検索・閲覧可能に。

**スコープ:**
- 前処理サービス（LibreOffice + pdf2image + python-docx/openpyxl）
  - ファイル → PDF → ページ画像
  - テキスト/表は構造化抽出
- Vision LLM ノードで図形を Mermaid 化
- マージ LLM が標準 Markdown を生成
- 登録 Bot に組み込み

**成果物:**
- `services/preprocessor/` (FastAPI)
- 登録 Bot YAML を v2 に

---

## Phase 3: 他チームへの展開 ⚪

**目的:** 別チームに「Adapter 差し替えで動く」状態でパッケージ提供。

**スコープ:**
- Filesystem (Git+Markdown+MkDocs) Adapter の実装
  - 同一実装で Obsidian Vault にも対応（`viewer_url` を `obsidian://` 形式に切替）
- セットアップ手順書
- IA 規約・ライティング規約・ページテンプレートの完成
- サンプルナレッジ（デモ用）

**成果物:**
- `services/docstore-filesystem/`（Git 公開サイト / Obsidian Vault 両対応）
- `conventions/` 一式
- `docs/setup-guide.md`

---

## 統一チャット（4アプリ → 1チャット） 🟢 v1 実機検証済

ユーザー向け入口を 1 つのチャットに統合し、裏で各機能に振り分ける。
**v1 実装済み・実機検証済み**（質問 / 登録 / 一括取り込みを統合。重複排除は管理者用に別置）。

- v1 は**決定的ルーティング**（添付有無・抽出文字数・明示キーワード）。
  エージェント的な自律判断は v2 以降で検討する。
- 各機能の中身（Adapter 契約・決定的コア・HITL の承認モデル）はそのまま流用。
  統合されたのは「入口」であり、疎結合の設計原則（design-principles.md）は変えていない。

→ 設計・検証結果は [unified-chat-design.md](unified-chat-design.md)。
成果物: `dify/unified-chat/`（ルーターコア）、`dify/workflows/unified-chat-bot.yml`（統合 DSL）。
