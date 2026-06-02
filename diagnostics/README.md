# diagnostics/

会社端末での実行結果を、開発用 PC に**まとめて持ち帰る**ための仕組み。

## なぜ必要か

開発体制上、本番の GROWI / Dify は会社端末からしか繋がらない。
会社端末 → 開発 PC へのファイル持ち出しは申請が要る（zip 形式）。
→ **1 回の持ち帰りで開発側が原因究明できるだけの情報を、自動で 1 つの zip にまとめる。**

## 使い方（会社端末）

1. GitHub から pull して最新化
2. 両サービスを起動（`.env` 設定済み前提）
   ```bash
   cd services/docstore-growi && uv run uvicorn app.main:app --port 8001 &
   cd services/sync          && uv run uvicorn app.main:app --port 8002 &
   ```
3. 診断バンドルを収集
   ```bash
   bash diagnostics/collect.sh
   ```
   ポートが違う場合:
   ```bash
   ADAPTER_URL=http://localhost:8001 SYNC_URL=http://localhost:8002 \
     bash diagnostics/collect.sh
   ```
4. 生成された `diagnostics/out/bundle-<日時>.zip` を申請して持ち帰る

## バンドルの中身

| ファイル | 内容 | 用途 |
|----------|------|------|
| `adapter-health.json` / `adapter-info.json` | GROWI Adapter の状態 | 疎通確認 |
| `sync-health.json` / `sync-info.json` | Sync Service の状態 | 疎通確認 |
| `growi-raw-pages.json` | GROWI ページ一覧の**生レスポンス** | mappers 調整の金脈 |
| `growi-raw-recent.json` | GROWI 最近更新の**生レスポンス** | 差分同期の検証 |
| `growi-raw-page-first.json` | GROWI 単一ページの**生レスポンス** | revision/body 形状確認 |
| `dify-raw-documents.json` | Dify ドキュメント一覧の**生レスポンス** | dify_client 調整 |
| `docstore-raw-pages.json` | DocStore 経由のページ一覧 | 変換後の確認 |
| `sync-dryrun-full.json` | dry-run 同期レポート | 何件 created/updated/deleted されるか |
| `logs/<service>/*.log` | 各サービスのログ | エラー詳細 |
| `environment.txt` | OS / Python / git rev | 再現環境の把握 |
| `env-presence.txt` | 環境変数の**設定有無のみ** | 設定漏れの確認 |
| `*.status` / `*.err` | 各リクエストの HTTP ステータス / curl エラー | 失敗箇所の特定 |

## 安全性

- **シークレットは収集しない。** トークン/APIキーの値は zip に含まれない。
  `env-presence.txt` は「SET / unset」だけを記録する。
- サービスのログにもシークレットは出さない設計（`logging_setup.py` 参照）。
- **GROWI/Dify のレスポンス本文（マニュアル生値）は含まれる。**
  会社データを持ち出す前提の運用であること（本プロジェクトではこの方針で合意済み）。

## debug エンドポイントの無効化

生レスポンスを返す `/debug/raw/*` は、本番常用では無効化できる:

```
# 各サービスの .env
DEBUG_ENDPOINTS_ENABLED=false
```

診断したいときだけ `true`（デフォルト）にする運用でよい。

## 開発 PC 側（持ち帰り後）

`bundle-<日時>.zip` を展開して中身を共有してくれれば、
`growi-raw-*.json` / `dify-raw-documents.json` を見て
`mappers.py` / `dify_client.py` のキー取り出しを実データに合わせて修正する。
