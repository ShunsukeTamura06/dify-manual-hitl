# services/

Dify とは独立して動く HTTP サービス群。

設計原則 [docs/design-principles.md](../docs/design-principles.md) に従い、各サービスは:

- 単一責任
- 契約付き API でのみ通信
- 単独起動・停止可能
- 設定は環境変数経由

## サービス一覧

| ディレクトリ | 役割 | 契約 |
|-------------|------|------|
| [docstore-growi/](docstore-growi/) | GROWI を DocStore API で見せる Adapter | [docstore-openapi.yaml](../contracts/docstore-openapi.yaml) |
| [sync/](sync/) | DocStore → Dify Knowledge の同期サービス | （内部） |

将来追加予定:

- `docstore-filesystem/`: Git + Markdown ファイル用 Adapter（Phase 3）
- `preprocessor/`: バイナリファイル前処理サービス（Phase 2）

## デプロイ方針

**Dify とは別の docker-compose で運用する**。

### 理由

- 設計原則「独立デプロイ可能」に沿う
- Dify を更新してもサービスは無影響
- 他チーム展開時、Dify はそのまま・サービスだけ持っていける
- サービス側だけ別ホストに切り出すなどの自由度がある

### docker compose で一括起動（推奨）

[docker-compose.yml](docker-compose.yml) で 2 サービスをまとめて起動できる。

```bash
cd services

# 各サービスの .env を用意して値を設定
cp docstore-growi/.env.example docstore-growi/.env
cp sync/.env.example          sync/.env
#  → GROWI_BASE_URL / GROWI_API_TOKEN
#  → DIFY_API_BASE_URL / DIFY_API_KEY / DIFY_DATASET_ID を設定

docker compose up -d --build

# 状態確認
docker compose ps
curl http://localhost:8002/health    # docstore_reachable / dify_reachable を確認
```

ポイント:
- **サービス間通信**: `sync → docstore-growi` は compose 内部 DNS
  (`http://docstore-growi:8001`) で接続。この URL は compose の `environment` で
  上書きするので、`sync/.env` の `DOCSTORE_URL` は気にしなくてよい。
- **ログ**: 各サービスの `logs/` をホストにマウント。診断バンドルで回収できる。
- **ヘルスチェック**: 両サービスに healthcheck を設定済み。`docker compose ps` で
  `healthy` を確認できる。

### Dify / GROWI への到達

いずれも各 `.env` の URL で指定する。Dify が同一ホストの別 compose にいる場合:

| 方法 | 設定 |
|------|------|
| (A) host 経由 | `.env` の `DIFY_API_BASE_URL=http://host.docker.internal:5001`（compose に `host-gateway` 設定済み） |
| (B) ネットワーク参加 | Dify の compose ネットワークに external 参加（docker-compose.yml 末尾コメント参照） |

GROWI は通常ホスト名 URL（例 `https://growi.internal`）で到達できるのでそのまま。

これにより:
- Dify は services の存在を知らない（疎結合）
- services は Dify を環境変数経由でしか知らない
- 一方のみ再起動・更新可能

### 個別起動（開発時）

compose を使わず個別に動かす場合の順序:

1. Dify を起動（既に稼働中ならスキップ）
2. `docstore-growi` を起動 → `/health` 確認
3. `sync` を起動 → `/sync` で初回同期
