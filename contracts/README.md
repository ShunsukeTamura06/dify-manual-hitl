# contracts/

コンポーネント間の**契約**を定義する。実装より先にここを更新する。

## 含まれるもの

| ファイル | 内容 |
|----------|------|
| [docstore-openapi.yaml](docstore-openapi.yaml) | DocStore Adapter の HTTP API 仕様。Wiki 実装を隠蔽する統一インターフェース |

将来追加予定:

- `preprocessor-openapi.yaml`: バイナリ → 構造化テキスト変換サービス (Phase 2)
- `knowledge-metadata-schema.json`: Dify Knowledge のメタデータスキーマ

## 編集ルール

設計原則 [docs/design-principles.md](../docs/design-principles.md) のルール 5「スキーマ変更はバージョニング」に従う:

- 新フィールド追加: 後方互換のためそのまま追加 OK
- 既存フィールド削除・型変更: バージョン分け（`/v1/` → `/v2/`）
- 廃止予定: deprecated マーク → 最低 1 サイクル猶予

## ローカルプレビュー

```bash
# Swagger UI で見る
docker run -p 8080:8080 -e SWAGGER_JSON=/spec/docstore-openapi.yaml \
  -v $(pwd)/contracts:/spec swaggerapi/swagger-ui
```

ブラウザで http://localhost:8080
