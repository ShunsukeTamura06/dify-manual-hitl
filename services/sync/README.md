# sync

DocStore Adapter の内容を Dify Knowledge に同期するサービス。

```
[DocStore Adapter] ──read──> [Sync Service] ──write──> [Dify Knowledge]
   (GROWI 等を抽象化)          (Wiki 非依存)            (Dify API)
```

## 責任範囲

| やること | やらないこと |
|----------|--------------|
| DocStore → Dify の突合・反映 | Wiki の編集（Adapter の仕事） |
| 作成・更新・孤立削除 | LLM 処理・ユーザー応答 |
| 差分／全件同期 | チャンク化・ベクトル化（Dify の仕事） |

## 状態を持たない設計

同期状態（page_id ↔ document_id の対応）は **Dify 自身が保持**する。
Dify Document 名に `{page_id}::{title}` の形式で page_id を埋め込み、
同期のたびに Dify のドキュメント一覧から対応を復元する。

→ このサービスは**ステートレス**。外部 DB 不要。再起動しても状態は失われない。

命名規則に合わないドキュメント（手動作成等）は同期対象外として**触らない**。

## 同期モード

| モード | 内容 | 用途 |
|--------|------|------|
| `full` | DocStore 全ページ vs Dify 全ドキュメントを突合。孤立削除も行う | 初回・定期フル同期・整合性修復 |
| `diff` | DocStore `/pages/changes` の差分のみ反映 | 日次バッチ・取りこぼし補修 |

両モードとも `dry_run: true` で「何が起きるか」だけ確認できる（書き込みなし）。

## エンドポイント

| メソッド | パス | 内容 |
|----------|------|------|
| POST | `/sync` | 同期トリガー（`{"mode": "full"}` 等） |
| GET | `/health` | DocStore と Dify への到達確認 |
| GET | `/info` | サービス情報 |

### 使用例

```bash
# 全件同期（dry-run でまず確認）
curl -X POST http://localhost:8002/sync \
  -H 'Content-Type: application/json' \
  -d '{"mode": "full", "dry_run": true}'

# 本番全件同期
curl -X POST http://localhost:8002/sync \
  -H 'Content-Type: application/json' \
  -d '{"mode": "full"}'

# 差分同期（前回同期時刻を since に渡す）
curl -X POST http://localhost:8002/sync \
  -H 'Content-Type: application/json' \
  -d '{"mode": "diff", "since": "2026-05-29T00:00:00+00:00"}'
```

## セットアップ

```bash
cp .env.example .env
# .env を編集:
#   DOCSTORE_URL        … GROWI Adapter の URL（例 http://localhost:8001）
#   DIFY_API_BASE_URL   … Dify の URL（例 http://localhost:5001）
#   DIFY_API_KEY        … Dify ナレッジ API キー
#   DIFY_DATASET_ID     … Phase 1a で作ったナレッジの ID

uv sync
uv run uvicorn app.main:app --reload --port 8002
```

API ドキュメント: http://localhost:8002/docs

## テスト

```bash
uv run pytest          # 突合ロジックを Fake クライアントで検証（ネットワーク不要）
uv run ruff check .
uv run mypy app
```

## cron での定期実行（例）

このサービス自身はスケジューラを持たない（単一責任）。外部 cron から叩く:

```cron
# 毎日 2:00 に差分同期（since は前回からの差分を運用側で管理 or full で代替）
0 2 * * * curl -sX POST http://localhost:8002/sync -H 'Content-Type: application/json' -d '{"mode":"full"}'
```

将来 webhook 受付やスケジュール内蔵が必要になれば別途検討（Phase 1b 後半）。

## 既知の制約

- **Dify API のバージョン差**: `create-by-text` 等のレスポンス形状はバージョンで
  異なる場合がある。→ **Dify 1.9.2（本番一致）で実機検証済み**。データセット API
  （`/v1/datasets`, Bearer dataset-key）の create/list/update/delete すべて想定通り動作し、
  `dify_client.py` は無修正で OK だった。GROWI → docstore-growi → sync → Dify 1.9.2 の
  一気通貫同期も成功確認済み。
  （補足: Dify 1.9.2 のコンソール API は HttpOnly クッキー + CSRF に変わったが、
  sync が使うのはデータセット API なので影響なし）
- **diff の since 管理**: 現状 since は呼び出し側が渡す。前回同期時刻の永続化は
  運用（cron スクリプト側）または将来の拡張で対応。当面は `full` で代替可能。
- **削除イベント**: DocStore Adapter 側が削除を検知できるかに依存する
  （GROWI Adapter は現状 recent ベースで削除を取りこぼす可能性 → `full` の孤立削除で補修）。
- **ネイティブメタデータ**: owner/canonical 等での Dify 検索フィルタは未対応。
  現状は本文冒頭にソースヘッダを埋め込む方式。Phase 2 で改善予定。
