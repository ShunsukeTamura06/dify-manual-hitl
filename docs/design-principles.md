# 設計原則: Loosely Coupled, Independently Replaceable

このシステムは複数の独立したコンポーネントで構成される。
**各コンポーネントが交換可能・独立デプロイ可能であること**を最優先の設計原則とする。

ここがブレると構成全体が崩れる。新しいアプリ・サービスを追加するたびに、この原則に違反していないかをチェックする。

---

## 5つの中核原則

1. **単一責任** — 1コンポーネント=1役割
2. **インターフェース越しのみ通信** — 内部実装に依存しない
3. **状態は外に持つ** — コンポーネント自体はステートレス
4. **独立デプロイ可能** — 他を止めずに更新できる
5. **個別に交換可能** — 別実装に差し替えても他に影響しない

---

## コンポーネント一覧と責任

| コンポーネント | 唯一の責任 | 実装例 |
|----------------|-----------|--------|
| 質問 Bot | 自然言語質問に Knowledge ベースで回答する | Dify Chatflow |
| 登録 Bot | アップロードファイルを整形して Wiki にドラフトを置く | Dify Chatflow |
| 同期 Workflow | Wiki の変更を Knowledge に反映する | Dify Workflow |
| 保守 Workflow | 重複・古さ・孤立を検知して通知する | Dify Workflow |
| DocStore Adapter | Wiki 実装を隠蔽し、統一 API で読み書きを提供 | FastAPI 等 |
| Preprocessor | バイナリファイル → 構造化テキスト + ページ画像 | FastAPI + LibreOffice |
| Wiki | マニュアル本体の保存・閲覧・編集・版管理 | GROWI / Git+MD / etc. |
| Knowledge (Dify) | RAG 検索用のベクトルインデックス | Dify Knowledge |

---

## 守るべき具体的ルール

### ルール 1: アプリ間で直接呼び出さない

```
❌ Bad
質問 Bot ──直接 API──> 登録 Bot
登録 Bot ──直接 API──> 同期 Workflow

✅ Good
質問 Bot ──read──> Knowledge <──write── 同期 Workflow
登録 Bot ──HTTP──> DocStore Adapter ──> Wiki
```

アプリ同士は**共有データ（Knowledge）か外部サービス（Adapter）越しにしか出会わない**。

### ルール 2: 通信はすべて契約付きの境界

| 境界 | 契約形式 |
|------|----------|
| Dify App ↔ DocStore Adapter | HTTP API（OpenAPI 仕様で定義） |
| Dify App ↔ Preprocessor | HTTP API（OpenAPI 仕様で定義） |
| Dify App ↔ Knowledge | メタデータスキーマで定義 |
| Wiki ↔ DocStore Adapter | Adapter 内に閉じ込める（外に漏らさない） |

**契約 = ドキュメント化されたインターフェース**。コードを読まないと分からない依存は NG。

### ルール 3: 「知っていてはいけないこと」を列挙する

各コンポーネントは以下を**知らずに動かせるべき**:

| コンポーネント | 知らないべきもの |
|----------------|------------------|
| 質問 Bot | Wiki 実装 (GROWI/Confluence/etc)、登録 Bot の存在、Adapter の内部 |
| 登録 Bot | 質問 Bot の存在、Wiki 実装、Knowledge 内部のチャンク戦略 |
| 同期 Workflow | LLM モデル、ユーザーの存在 |
| 保守 Workflow | LLM モデル（必要なら別 Workflow に切り出し） |
| DocStore Adapter | Dify の存在、LLM の存在、ベクトル DB の存在 |
| Preprocessor | Wiki の存在、Dify の存在 |

→ **「これを知らずに動くか？」を常に自問**する。知っていたら結合が強すぎる。

### ルール 4: 設定は外から注入

```yaml
❌ Bad (Hardcoded)
dataset_ids: ["abc123..."]
adapter_url: "http://growi-adapter.internal:8000"

✅ Good (Injected)
dataset_ids: ["{{ env.MANUALS_DATASET_ID }}"]
adapter_url: "{{ env.DOCSTORE_ADAPTER_URL }}"
```

Dify は Environment Variables 機能あり。本番では必ずこちらを使う。

### ルール 5: スキーマ変更はバージョニング

Knowledge のメタデータスキーマや Adapter API を変えるときは:

- 新フィールドは追加（破壊しない）
- 破壊変更はバージョン分け（`/v1/` → `/v2/`）
- 移行期間中は両方サポート
- 廃止予定は deprecated マーク後、最低 1 サイクル猶予

---

## アンチパターン

| アンチパターン | なぜダメか |
|----------------|------------|
| 登録 Bot が質問 Bot を呼ぶ | アプリ間結合の発生 |
| Adapter が Dify の内部 API を直叩き | Wiki との距離感が崩れる |
| 質問 Bot が Wiki 特有の URL 形式を生成 | Wiki 差し替え時に書き換え必要 |
| 共通ユーティリティ関数を全アプリで共有 | 変更すると全部影響 |
| Knowledge 更新を質問 Bot がやる | 責任の二重化 |
| 環境固有のホスト名や ID を YAML にハードコード | 環境移行で必ず壊れる |
| メタデータ未定義のまま運用開始 | 後から検索精度を上げられない |
| Adapter から戻る `viewer_url` を Dify 側で再加工 | Wiki が変わると壊れる |

---

## 新しいコンポーネントを追加するときのチェックリスト

新規アプリ・サービスを作るとき、以下を全部 ✅ できるか確認:

- [ ] このコンポーネントの責任は**1つ**に絞れているか
- [ ] 他のアプリを直接呼んでいないか（Knowledge / Adapter 経由か）
- [ ] 設定値は環境変数経由か（ハードコード無いか）
- [ ] Wiki 実装に依存していないか（Adapter 越しか）
- [ ] LLM プロバイダに依存していないか（差し替え可能か）
- [ ] 単独で起動・停止できるか（他を巻き込まないか）
- [ ] 通信相手の API 契約はドキュメント化されているか
- [ ] 失敗時に他のコンポーネントを巻き込まないか（fault isolation）

1 つでも ✕ があれば設計を見直す。

---

## 既存ファイルへの含意

| ファイル | 現状 | 改善方針 |
|----------|------|----------|
| `dify/workflows/phase1a-qa-bot.yml` の `dataset_ids` | プレースホルダ文字列 | 本番では Dify Environment Variables 経由に |
| `dify/workflows/phase1a-qa-bot.yml` の Reranker 設定 | プレースホルダ | ワークスペース設定 or 環境変数化 |
| 将来の Wiki URL の組み立て | （未実装） | Adapter から返る `viewer_url` をそのまま使う。Dify 側で組み立てない |
| 将来の DocStore Adapter | （未実装） | 先に OpenAPI 仕様を書いてから実装 |

---

## 議論ログ

この原則は議論で更新されていく。重要な決定は以下に追記:

- 2026-05-29: 初版作成。Loosely Coupled / Independently Replaceable を中核原則として確立
