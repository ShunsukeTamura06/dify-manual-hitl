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
│ B. Sync Service       … ① → ② の Knowledge へ自動同期      │
│    （定期 cron + GROWI webhook の二層）                    │
│ C. 完全 bot（1 Chatflow） … ② にインポートする単一チャット  │
│    質問・登録・一括取込・重複排除・承認待ち確認を1窓口で    │
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

Dify「スタジオ → アプリ作成 → DSL からインポート」で、**まず 1 つだけ**インポートすれば動く:

- **[dify/workflows/unified-chat-bot.yml](dify/workflows/unified-chat-bot.yml)**（完全 bot・推奨）
  質問・登録・一括取り込み・重複排除の提示/統合・承認待ち確認の 5 機能を
  **1 つのチャット窓口**で受ける。ユーザーの発話や添付ファイルから LLM 意図分類 +
  決定的サニタイズでルーティングする（詳細は
  [docs/unified-chat-design.md](docs/unified-chat-design.md)）。エンドユーザーが
  使うのはこれ 1 本でよい。

インポート後、**環境に合わせて差し替える**のは以下だけ:

| 箇所 | 差し替え内容 |
|-----|-------------|
| LLM ノード（8 箇所）のモデル | あなたの LLM（例 gpt-4o-mini / claude 等）。既定は gpt-4o-mini |
| `q_knowledge_retrieval` / `similar_search` の `dataset_ids` | `REPLACE_WITH_YOUR_DATASET_ID` → Step 3 の Dataset ID（**2 箇所とも**同じナレッジに向ける） |
| `q_knowledge_retrieval` の Reranker | Reranker 未設定なら `reranking_enable: false` + `weighted_score` に（`similar_search` と同じ形）。設定済みなら `REPLACE_WITH_RERANKER_PROVIDER` / `REPLACE_WITH_RERANKER_MODEL` を実値に |
| environment_variables の `DOCSTORE_URL` / `DOCSTORE_API_KEY` | Adapter の到達 URL / API キー（Step 2 の到達性、`ADAPTER_API_KEY` を設定した場合のみキー必須） |

> 個別 Bot（[phase1a-qa-bot.yml](dify/workflows/phase1a-qa-bot.yml) /
> [phase1c-registration-bot.yml](dify/workflows/phase1c-registration-bot.yml) /
> [bulk-import-bot.yml](dify/workflows/bulk-import-bot.yml) /
> [dedup-bot.yml](dify/workflows/dedup-bot.yml)）は unified-chat-bot.yml の
> **構成部品のソース**（`dify/unified-chat/tools/build_dsl.py` が合成する元 DSL）。
> 動作確認や機能単体のデバッグには使えるが、通常のデプロイでは不要。

詳細は [dify/workflows/phase1c-setup.md](dify/workflows/phase1c-setup.md)、
[dify/workflows/README.md](dify/workflows/README.md)。

### Step 5. 同期を自動化する

初回（Wiki の既存ページを Dify に取り込む）:
```bash
curl -X POST http://<sync>/sync -H 'Content-Type: application/json' -d '{"mode":"full"}'
```

以降は 2 層の自動反映で「Wiki で公開 → 質問 Bot が拾う」まで人手を挟まない
（`services/docker-compose.yml` に組み込み済み）:

1. **定期 cron**（`sync-cron` コンテナ）: `SYNC_CRON_INTERVAL` 秒ごと（既定 900 秒）に
   `POST /sync {"mode":"full"}` を自動実行。取りこぼしの保険。
2. **GROWI webhook**: ページ公開のたびに GROWI から `POST /webhook/growi` を叩かせ、
   即時に差分同期。`GROWI_WEBHOOK_TOKEN` を設定すると認証必須になる
   （同時実行はロックでスキップ、二重実行しない）。

設定は [services/sync/README.md](services/sync/README.md) の「自動同期」節を参照。

---

## 動作確認（一気通貫）

1. 完全 bot にマニュアル（ファイル）を添付して送る → Wiki に下書き（draft）が作られる。
   類似ページがあれば併せて提示される（ブロックはしない）
2. 完全 bot に「承認待ち一覧を見せて」と聞く → 下書き中のページが一覧表示される
   （`GET /pages/pending-approval`）
3. 内容を確認し、`status: published` にして公開する（これが HITL の承認操作）。
   GROWI で frontmatter を直接編集してもよいが、YAML の手編集は誤操作のリスクが
   あるため、Adapter の `GET /approvals` （承認待ち一覧 + ボタン1つで公開）を
   使うのが簡単（[services/docstore-growi/README.md](services/docstore-growi/README.md)）。
   > `/approvals` を使う場合の注意: Dify が Adapter を叩く `DOCSTORE_URL`
   > （例 `http://docstore-growi:8001`）は Docker 内部専用で、人のブラウザからは
   > 開けない。社員が `/approvals` を開けるようにするには、Adapter のポートを
   > 社内ネットワークなど**ブラウザから到達できる別のアドレス**で公開すること
   > （`DOCSTORE_URL` 自体は変更不要。あくまで人が開く URL が別に要るという話）。
4. 自動同期（cron または GROWI webhook。手動なら `POST /sync`）で Dify Knowledge に反映
5. 完全 bot に質問する → 出典 URL + 最終更新日つきで回答が返る。古い情報には
   自動で「最新か確認を」の注記が付く
6. （任意）大きなファイルを添付すると自動で分割登録、「重複を確認して」と聞くと
   類似ページのクラスタを確信度つきで提示し、「統合して」で高確信クラスタを
   実際に統合（統合先は draft、統合元は deprecated + リダイレクト注記）。統合直後は
   欠落の疑いがあれば統合先ページに自動で警告バナーを入れる

ローカルでこの全ループを実機検証済み（[local-dev/README.md](local-dev/README.md)）。

---

## 移植性チェックリスト（別の組織・別の Wiki / LLM に渡すとき）

- [ ] Wiki 実装に対応する DocStore Adapter があるか（無ければ契約に沿って実装）
- [ ] `sync/.env` の Dify 接続先・キーが新環境のものか
- [ ] Dify に LLM + 埋め込みモデルが設定されているか
- [ ] Adapter が Dify のワークフローから到達できるネットワーク配置か
- [ ] unified-chat-bot.yml をインポートし、モデル/`dataset_ids`（2 箇所）/
      `DOCSTORE_URL` を差し替えたか
- [ ] 初回 full sync が成功し、完全 bot が出典付きで答えるか
- [ ] 定期 cron（`sync-cron`）または GROWI webhook のどちらかが動いているか
      （公開してもいつまでも反映されない、を防ぐ）

このチェックリストが全部 ✅ なら、その組織で動く。
特定ベンダーへの依存は Adapter と Dify のモデル設定に閉じている。
