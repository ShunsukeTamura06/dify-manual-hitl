# 設定リファレンス

全設定は環境変数（各サービスの `.env`）で注入する。ハードコードは無い。
これにより、どの組織・どの Wiki / LLM 環境でも設定だけで動かせる。

## DocStore Adapter（GROWI 版）: `services/docstore-growi/.env`

| 変数 | 必須 | 既定 | 説明 |
|------|------|------|------|
| `GROWI_BASE_URL` | ✓ | — | Wiki(GROWI) のベース URL（末尾スラッシュなし） |
| `GROWI_API_TOKEN` | ✓ | — | Wiki の API トークン（秘密。`.env` のみ） |
| `MANUAL_ROOT_PATH` |  | `/manuals` | 対象にするマニュアルのルートパス。空で全ページ |
| `ADAPTER_API_KEY` | 推奨 | （空=認証なし） | 設定すると全エンドポイント（`/health` 除く）で `X-API-Key` を要求。Wiki への書込 API を無認証で公開しないため、共有ネットワークでは必ず設定する。ただし `/approvals`（承認ボタン画面）はブラウザがヘッダを送れないため、`X-API-Key` の代わりに `?key=<ADAPTER_API_KEY>` クエリでも通す |
| `PORT` |  | `8001` | 待ち受けポート |
| `LOG_LEVEL` |  | `INFO` | ログレベル |
| `LOG_DIR` |  | `logs` | ログ出力先 |
| `DEBUG_ENDPOINTS_ENABLED` |  | `false` | `/debug/raw/*`（生レスポンス取得）の有効化。診断時のみ `true` |
| `REQUEST_TIMEOUT` |  | `30` | Wiki API のタイムアウト秒 |

> 別の Wiki を使う場合は、その Wiki 用 Adapter の `.env`（接続情報のキー名は
> Adapter ごとに異なる）を設定する。Sync 以降は Wiki 実装に非依存。

## Sync Service: `services/sync/.env`

| 変数 | 必須 | 既定 | 説明 |
|------|------|------|------|
| `DOCSTORE_URL` | ✓ | `http://localhost:8001` | DocStore Adapter の到達 URL |
| `DOCSTORE_API_KEY` |  | （空） | Adapter の `ADAPTER_API_KEY` と同じ値（`X-API-Key` として送る） |
| `SYNC_API_KEY` | 推奨 | （空=認証なし） | 設定すると全エンドポイント（`/health` 除く）で `X-API-Key` を要求 |
| `SYNC_EXCLUDE_STATUSES` |  | `draft,deprecated` | 同期対象外とする `metadata.status`。下書き・退役ページを検索に出さない（HITL） |
| `DIFY_API_BASE_URL` | ✓ | `http://localhost:5001` | Dify の URL（`/v1` は付けない） |
| `DIFY_API_KEY` | ✓ | — | Dify データセット API キー（秘密） |
| `DIFY_DATASET_ID` | ✓ | — | 同期先ナレッジの Dataset ID |
| `DIFY_INDEXING_TECHNIQUE` |  | `high_quality` | `high_quality`(埋め込み必要) / `economy`(不要) |
| `EMBED_SOURCE_HEADER` |  | `true` | 本文冒頭に出典ヘッダ（URL・更新日）を埋め込むか |
| `GROWI_WEBHOOK_TOKEN` |  | （空=認証なし） | `POST /webhook/growi` の `?token=` 検証用。GROWI 側の webhook 設定に同じ値を入れる |
| `WEBHOOK_SYNC_MODE` |  | `full` | webhook 起動時の同期モード（`full` / `diff`） |
| `PORT` |  | `8002` | 待ち受けポート |
| `LOG_LEVEL` |  | `INFO` | ログレベル |
| `LOG_DIR` |  | `logs` | ログ出力先 |
| `DEBUG_ENDPOINTS_ENABLED` |  | `false` | `/debug/raw/*` の有効化。診断時のみ `true` |
| `REQUEST_TIMEOUT` |  | `60` | 外部 API のタイムアウト秒 |

## 定期同期 cron: `services/docker-compose.yml` の `sync-cron`

| 変数 | 必須 | 既定 | 説明 |
|------|------|------|------|
| `SYNC_CRON_INTERVAL` |  | `900`（秒） | `POST /sync {"mode":"full"}` を実行する間隔。GROWI webhook と併用する二重の保険 |
| `SYNC_API_KEY` |  | （空） | Sync 側で認証を有効にした場合、cron からのリクエストにも同じ値を設定 |

## Dify 側の設定（コードではなく Dify 管理画面 / API）

| 項目 | どこで | 説明 |
|------|--------|------|
| LLM プロバイダ | モデルプロバイダ | 任意の LLM（OpenAI/Anthropic/ローカル）。Bot の LLM ノードで選択 |
| 埋め込みモデル | モデルプロバイダ | high_quality 検索に必要 |
| ナレッジ(Dataset) | ナレッジ | 同期先。high_quality + 埋め込み指定で作成 |
| データセット API キー | ナレッジ → API | `sync` の `DIFY_API_KEY` に設定 |

## 完全 bot（unified-chat-bot.yml）のインポート後に環境差し替えする箇所

| ノード | 差し替え |
|--------|----------|
| LLM（8 箇所） | あなたの LLM モデルを選択（既定 gpt-4o-mini） |
| `q_knowledge_retrieval` / `similar_search` | `dataset_ids` を**両方とも**あなたのナレッジに。Reranker 無しなら `q_knowledge_retrieval` も weighted_score に |
| environment_variables | `DOCSTORE_URL` を Adapter の到達 URL に。Adapter の認証を有効にした場合は `DOCSTORE_API_KEY` にも同じ値を設定 |

詳細は [DEPLOYMENT.md](../DEPLOYMENT.md) の Step 4。

## 秘密情報の扱い

- トークン/API キーの**値はリポジトリに置かない**（`.env` は gitignore 済み）。
- ログ・診断バンドルにも秘密は出さない設計（`env-presence` は設定有無のみ記録）。
- 詳細は [diagnostics/README.md](../diagnostics/README.md)。
