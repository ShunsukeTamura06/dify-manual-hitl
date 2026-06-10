# デプロイガイド（汎用）

このシステムは特定の製品・ベンダーに縛られない。
**Wiki + Dify + LLM API キー**さえ用意できれば、どの組織の環境でも動かせる。

このガイドは「自社の○○に合わせる」手順ではなく、
**3 つの外部依存を差し込めば動く**ことを示す汎用手順。

---

## アーキテクチャと外部依存

```
┌─ 各組織が用意する外部依存 ───────────────────────────────┐
│ ① Wiki（Single Source of Truth）                        │
│    人が読み書きするマニュアル本体。実装は何でもよい:      │
│    GROWI / Confluence / Notion / Git+Markdown / 共有FS  │
│ ② Dify インスタンス                                      │
│    LLM 編成 + Knowledge(RAG)。セルフホスト/Cloud いずれも │
│ ③ LLM プロバイダの API キー                              │
│    Dify に設定。OpenAI / Anthropic / ローカル(Ollama) 等 │
└──────────────────────────────────────────────────────────┘
                  ↑           ↑              ↑
┌─ このリポジトリが提供する成果物 ─────────────────────────┐
│ A. DocStore Adapter   … ① の Wiki を統一 API で隠蔽       │
│ B. Sync Service       … ① → ② の Knowledge へ同期         │
│ C. Bot DSL（2 種）    … ② にインポートする登録/質問 Bot    │
└──────────────────────────────────────────────────────────┘
```

**差し替えポイント:**
- Wiki を変える → 対応する DocStore Adapter を選ぶ/書く（契約は
  [contracts/docstore-openapi.yaml](contracts/docstore-openapi.yaml)）。他は不変。
- LLM を変える → Dify のモデルプロバイダ設定を変えるだけ。コードは不変。

---

## 前提（組織側で用意するもの）

| 依存 | 必要なもの |
|------|-----------|
| Wiki | アクセス可能な URL と API 認証情報（例: GROWI なら API トークン） |
| Dify | アクセス可能な URL、管理者アカウント、ナレッジ API キー |
| LLM | LLM プロバイダの API キー（+ 埋め込みモデル。high_quality 検索に必要） |

> 埋め込み: high_quality な検索には埋め込みモデルが要る。LLM が埋め込みを
> 提供しない場合（例: Anthropic）は OpenAI/Cohere 等のキーを別途用意するか、
> ローカル埋め込み（Ollama 等）を使う。検索品質を問わなければ economy（埋め込み不要）も可。

---

## デプロイ手順

### Step 1. DocStore Adapter と Sync を設定

```bash
cd services
cp docstore-growi/.env.example docstore-growi/.env
cp sync/.env.example          sync/.env
```

`docstore-growi/.env`（Wiki が GROWI の場合）:
```
GROWI_BASE_URL=<あなたの Wiki の URL>
GROWI_API_TOKEN=<Wiki の API トークン>
```
> 別の Wiki を使うなら、その Wiki 用の Adapter（`services/docstore-<wiki>/`）を
> 用意し、同様に設定する。Sync 以降は Wiki 実装を一切知らない。

`sync/.env`:
```
DOCSTORE_URL=http://docstore-<wiki>:8001   # Adapter の到達 URL（下の「ネットワーク」参照）
DIFY_API_BASE_URL=<あなたの Dify の URL>    # 例 http://dify-nginx もしくは https://dify.example.com
DIFY_API_KEY=<Dify のデータセット API キー> # Step 3 で発行
DIFY_DATASET_ID=<Step 3 のナレッジ ID>
DIFY_INDEXING_TECHNIQUE=high_quality        # 埋め込み無しなら economy
```

設定項目の全量は [docs/configuration.md](docs/configuration.md) を参照。

### Step 2. Adapter と Sync を起動（ネットワークが肝）

```bash
docker compose up -d --build
```

**ネットワーク要件（重要・汎用）:**
登録 Bot の「Wiki に書き込む」処理は、**Dify のワークフロー HTTP リクエストから
Adapter に到達できる**必要がある。Dify を Docker で動かしている場合、Dify は
HTTP リクエストを SSRF プロキシ経由で出すため、以下のいずれかにする:

- (A) Adapter を **Dify と同じ Docker ネットワークに参加**させ、
  コンテナ名で到達させる（例 `http://docstore-growi:8001`）。**推奨・確実**。
- (B) Adapter を Dify から到達可能なホスト/URL に置き、その URL を使う。

compose でのネットワーク参加方法は [services/README.md](services/README.md) と
`services/docker-compose.yml` のコメントを参照（外部ネットワーク名を環境変数で指定）。

### Step 3. Dify にナレッジ（Knowledge）を用意

Dify 管理画面、またはデータセット API で:
1. LLM プロバイダと**埋め込みモデル**を設定（モデルプロバイダ画面）
2. ナレッジを作成（high_quality + 埋め込みモデル指定）
3. **データセット API キー**を発行（ナレッジ → API）
4. ナレッジの **Dataset ID** を控える

→ この 2 つ（API キー / Dataset ID）を `sync/.env` に設定。

### Step 4. Bot を Dify にインポート

Dify「スタジオ → アプリ作成 → DSL からインポート」で 2 つ:
- 質問 Bot: [dify/workflows/phase1a-qa-bot.yml](dify/workflows/phase1a-qa-bot.yml)
- 登録 Bot: [dify/workflows/phase1c-registration-bot.yml](dify/workflows/phase1c-registration-bot.yml)

インポート後、**環境に合わせて差し替える**のは以下だけ:

| Bot | 差し替え箇所 |
|-----|-------------|
| 共通 | LLM ノードのモデル（あなたの LLM。例 gpt-4o-mini / claude 等） |
| 質問 Bot | Knowledge Retrieval のナレッジ（Step 3）。Reranker 未設定なら検索を weighted_score に |
| 登録 Bot | environment_variables の `DOCSTORE_URL`（Adapter の到達 URL） |

詳細は [dify/workflows/phase1c-setup.md](dify/workflows/phase1c-setup.md)、
[dify/workflows/README.md](dify/workflows/README.md)。

### Step 5. 初回同期 + 定期実行

```bash
# 初回（Wiki の既存ページを Dify に取り込む）
curl -X POST http://<sync>/sync -H 'Content-Type: application/json' -d '{"mode":"full"}'
```

定期実行は外部 cron で `POST /sync` を叩く（Sync 自身はスケジューラを持たない）。
例は [services/sync/README.md](services/sync/README.md)。

---

## 動作確認（一気通貫）

1. 登録 Bot にマニュアル（ファイル）を投げる → Wiki に下書きが作られる
2. Wiki で内容を確認して公開する（HITL）
3. 同期する（cron もしくは手動 `POST /sync`）
4. 質問 Bot に質問する → 出典付きで回答が返る

ローカルでこの全ループを実機検証済み（[local-dev/README.md](local-dev/README.md)）。

---

## 移植性チェックリスト（別の組織・別の Wiki / LLM に渡すとき）

- [ ] Wiki 実装に対応する DocStore Adapter があるか（無ければ契約に沿って実装）
- [ ] `sync/.env` の Dify 接続先・キーが新環境のものか
- [ ] Dify に LLM + 埋め込みモデルが設定されているか
- [ ] Adapter が Dify のワークフローから到達できるネットワーク配置か
- [ ] Bot DSL をインポートし、モデル/ナレッジ/DOCSTORE_URL を差し替えたか
- [ ] 初回 full sync が成功し、質問 Bot が出典付きで答えるか

このチェックリストが全部 ✅ なら、その組織で動く。
特定ベンダーへの依存は Adapter と Dify のモデル設定に閉じている。
