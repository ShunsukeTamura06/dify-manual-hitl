# docstore-growi

GROWI を [DocStore Adapter API](../../contracts/docstore-openapi.yaml) として公開するサービス。

呼び出し側（Sync Service、登録 Bot 等）は GROWI を直接知らず、この Adapter 越しに読み書きする。
別の Wiki に乗り換えるときは、この Adapter を別実装に差し替えるだけ。

## 責任範囲

| やること | やらないこと |
|----------|--------------|
| GROWI API のラップ | Dify との通信（Sync Service の仕事） |
| GROWI JSON ↔ DocStore モデルの変換 | ベクトル化・検索（Dify の仕事） |
| frontmatter のパース/生成 | LLM 処理（登録 Bot の仕事） |

## 構成

```
app/
├── main.py          # FastAPI エントリ
├── settings.py      # 環境変数読み込み
├── models.py        # DocStore API のデータモデル（契約に対応）
├── growi_client.py  # GROWI REST API クライアント（GROWI 固有知識をここに隔離）
├── mappers.py       # GROWI ↔ DocStore 変換
├── deps.py          # DI
└── routes/
    ├── pages.py     # /pages CRUD
    ├── changes.py   # /pages/changes 差分検知
    └── meta.py      # /health, /info
tests/
└── test_mappers.py  # 変換ロジックの単体テスト（GROWI 実機不要）
```

## セットアップ

### 1. 環境変数を設定

```bash
cp .env.example .env
```

`.env` を編集して GROWI の接続情報を設定:

```
GROWI_BASE_URL=https://your-growi.example.com
GROWI_API_TOKEN=（GROWI で発行したトークンをここに貼る）
```

**GROWI API トークンの取得方法:**
1. GROWI にログイン
2. 右上アイコン → 個人設定 → API 設定
3. 「API Token 発行」→ 生成された文字列をコピー（再表示不可なので注意）

### 2. 依存インストール

```bash
uv sync
```

### 3. 起動

```bash
uv run uvicorn app.main:app --reload --port 8001
```

### 4. 動作確認

```bash
# Adapter 自身のメタ情報（GROWI 接続不要）
curl http://localhost:8001/info

# ヘルスチェック（GROWI 到達性を含む）
curl http://localhost:8001/health

# ページ一覧（GROWI 接続が必要）
curl "http://localhost:8001/pages?path_prefix=/manuals"
```

API ドキュメント（Swagger UI）: http://localhost:8001/docs

## テスト

```bash
# 変換ロジックの単体テスト（GROWI 実機なしで動く）
uv run pytest

# Lint / 型チェック
uv run ruff check .
uv run mypy app
```

## Docker

```bash
docker build -t docstore-growi .
docker run -p 8001:8001 --env-file .env docstore-growi
```

## GROWI 7.4.2 で検証済みの API 仕様

ローカルの実 GROWI 7.4.2 に対して全エンドポイントの動作を確認済み
（health / create / list / get / update / delete + frontmatter 往復 + 表保持）。
判明したバージョン依存の要点:

| 操作 | エンドポイント / 形式 | 備考 |
|------|----------------------|------|
| 作成 | `POST /_api/v3/page`（**単数**） | 複数形 `/pages` は 404 |
| 取得 | `GET /_api/v3/page?pageId=` | `revision` は dict（`body` あり） |
| 一覧 | `GET /_api/v3/pages/list?path=` | `revision` は **文字列(ID)**。本文なし → title はパス由来 |
| 更新 | `PUT /_api/v3/page` {pageId, body, revisionId} | revisionId 不一致で 409 |
| 削除 | `POST /_api/v3/pages/delete` {pageIdToRevisionIdMap:{id:rev}} | `{pageId,revisionId}` だと 400 |
| 死活 | `GET /_api/v3/healthcheck` | `{"status":"OK"}` |

## 注意点・既知の制約

- **削除はソフト削除**: GROWI の delete は既定でゴミ箱（/trash）へ移動する。
  pageId での GET は引き続き解決するが、`/manuals` 配下の一覧からは消えるため、
  同期の孤立削除（Dify から除去）は正しく機能する。完全削除が必要なら
  `isCompletely` オプションの追加を検討。
- **添付ファイル**: 現状 `attachments` は空配列。Phase 2（画像対応）で実装予定。
- **変更検知**: GROWI の recent API を polling する方式。削除イベントは recent に
  出ないため取りこぼす → `full` 同期の孤立削除で補修する。
- **frontmatter**: GROWI 本文の先頭に YAML frontmatter を埋め込む運用前提。
  GROWI ネイティブのタグ機能とは別管理。読み出し時に frontmatter を metadata に復元する。
