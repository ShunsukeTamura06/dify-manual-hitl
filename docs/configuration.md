# 設定リファレンス

全設定は環境変数（各サービスの `.env`）で注入する。ハードコードは無い。
これにより、どの組織・どの Wiki / LLM 環境でも設定だけで動かせる。

## DocStore Adapter（GROWI 版）: `services/docstore-growi/.env`

| 変数 | 必須 | 既定 | 説明 |
|------|------|------|------|
| `GROWI_BASE_URL` | ✓ | — | Wiki(GROWI) のベース URL（末尾スラッシュなし） |
| `GROWI_API_TOKEN` | ✓ | — | Wiki の API トークン（秘密。`.env` のみ） |
| `MANUAL_ROOT_PATH` |  | `/manuals` | 対象にするマニュアルのルートパス。空で全ページ |
| `PORT` |  | `8001` | 待ち受けポート |
| `LOG_LEVEL` |  | `INFO` | ログレベル |
| `LOG_DIR` |  | `logs` | ログ出力先 |
| `DEBUG_ENDPOINTS_ENABLED` |  | `true` | `/debug/raw/*`（生レスポンス取得）の有効化。本番常用は `false` 可 |
| `REQUEST_TIMEOUT` |  | `30` | Wiki API のタイムアウト秒 |

> 別の Wiki を使う場合は、その Wiki 用 Adapter の `.env`（接続情報のキー名は
> Adapter ごとに異なる）を設定する。Sync 以降は Wiki 実装に非依存。

## Sync Service: `services/sync/.env`

| 変数 | 必須 | 既定 | 説明 |
|------|------|------|------|
| `DOCSTORE_URL` | ✓ | `http://localhost:8001` | DocStore Adapter の到達 URL |
| `DIFY_API_BASE_URL` | ✓ | `http://localhost:5001` | Dify の URL（`/v1` は付けない） |
| `DIFY_API_KEY` | ✓ | — | Dify データセット API キー（秘密） |
| `DIFY_DATASET_ID` | ✓ | — | 同期先ナレッジの Dataset ID |
| `DIFY_INDEXING_TECHNIQUE` |  | `high_quality` | `high_quality`(埋め込み必要) / `economy`(不要) |
| `EMBED_SOURCE_HEADER` |  | `true` | 本文冒頭に出典ヘッダ（URL・更新日）を埋め込むか |
| `PORT` |  | `8002` | 待ち受けポート |
| `LOG_LEVEL` |  | `INFO` | ログレベル |
| `LOG_DIR` |  | `logs` | ログ出力先 |
| `DEBUG_ENDPOINTS_ENABLED` |  | `true` | `/debug/raw/*` の有効化 |
| `REQUEST_TIMEOUT` |  | `60` | 外部 API のタイムアウト秒 |

## Dify 側の設定（コードではなく Dify 管理画面 / API）

| 項目 | どこで | 説明 |
|------|--------|------|
| LLM プロバイダ | モデルプロバイダ | 任意の LLM（OpenAI/Anthropic/ローカル）。Bot の LLM ノードで選択 |
| 埋め込みモデル | モデルプロバイダ | high_quality 検索に必要 |
| ナレッジ(Dataset) | ナレッジ | 同期先。high_quality + 埋め込み指定で作成 |
| データセット API キー | ナレッジ → API | `sync` の `DIFY_API_KEY` に設定 |

## Bot DSL のインポート後に環境差し替えする箇所

| Bot | ノード | 差し替え |
|-----|--------|----------|
| 質問/登録 共通 | LLM | あなたの LLM モデルを選択 |
| 質問 | Knowledge Retrieval | `dataset_ids` をあなたのナレッジに。Reranker 無しなら検索を weighted_score に |
| 登録 | environment_variables | `DOCSTORE_URL` を Adapter の到達 URL に |

## 秘密情報の扱い

- トークン/API キーの**値はリポジトリに置かない**（`.env` は gitignore 済み）。
- ログ・診断バンドルにも秘密は出さない設計（`env-presence` は設定有無のみ記録）。
- 詳細は [diagnostics/README.md](../diagnostics/README.md)。
