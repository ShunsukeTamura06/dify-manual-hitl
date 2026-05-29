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

### 物理構成

同一ホストでも別ホストでも可。同一ホストの場合は Docker external network で繋ぐ:

```yaml
# services/docker-compose.yml (将来作成)
networks:
  shared:
    external: true
    name: dify-net   # Dify の docker-compose が作るネットワーク

services:
  docstore-growi:
    build: ./docstore-growi
    networks: [shared]
    environment:
      - GROWI_BASE_URL=https://growi.internal
      - GROWI_ACCESS_TOKEN=${GROWI_ACCESS_TOKEN}

  sync:
    build: ./sync
    networks: [shared]
    environment:
      - DOCSTORE_URL=http://docstore-growi:8001
      - DIFY_API_URL=http://dify-api:5001   # Dify ネットワーク内
      - DIFY_API_KEY=${DIFY_API_KEY}
      - DIFY_DATASET_ID=${DIFY_DATASET_ID}
```

これにより:
- Dify は services の存在を知らない（疎結合）
- services は Dify を環境変数経由でしか知らない
- 一方のみ再起動・更新可能

## 開発時の起動順序

1. Dify を起動（既に稼働中ならスキップ）
2. `docstore-growi` を起動 → ヘルスチェック
3. `sync` を起動 → 初回同期実行
