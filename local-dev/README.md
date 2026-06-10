# local-dev: フルスタックをこの PC で動かす

Dify + GROWI + 本リポジトリのサービス（docstore-growi / sync）を
**この開発 PC 上で一気通貫テスト**するための構成。

会社端末でしか動かせなかった実機テストの大半をローカルで潰し、
最終確認だけ会社端末で行う（本番とバージョンを合わせれば差はほぼ消える）。

## 構成（3 スタックを host.docker.internal で接続）

```
[Dify]            published :5001 (API) / :80 (web)
[GROWI]           published :3000
[services]        published :8001 (adapter) / :8002 (sync)

相互到達は host.docker.internal:<ポート>（Mac/Docker Desktop）
```

各スタックは独立した compose。設計原則「独立デプロイ可能」を保ったまま、
公開ポート経由で疎通する（shared network 不要）。

## バージョン方針

**本番の Dify / GROWI と同じバージョンに固定**する。本番は以下:
- **Dify: 1.9.2**（公式 self-host compose のタグを 1.9.2 に）
- **GROWI: 7.4.2**（`docker-compose.growi.yml` で固定済み）

→ ローカルで通れば本番でもほぼそのまま通る（API 形状差が消える）。

> 注意: Dify は 1.x で API が 0.x から変わっている。Knowledge API のレスポンス
> 形状が `dify_client.py` の想定と異なる場合は、ローカル 1.9.2 で実際に叩いて調整する。

## LLM / 埋め込み

この PC は外部 API に制限なく到達できる。Dify の「モデルプロバイダー」設定で:
- LLM: **Anthropic Claude**（個人 API キー）
- 埋め込み: OpenAI `text-embedding-3-large` / Cohere / その他（外部 API でよい）
- Rerank: Cohere Rerank 等（任意）

API キーは Dify の管理画面に入れる（このリポジトリには置かない）。

---

## 起動手順

### 1. GROWI を起動

```bash
cd local-dev
GROWI_VERSION=<本番と同じ> docker compose -f docker-compose.growi.yml up -d
```

- http://localhost:3000 にアクセスし、管理者アカウントを作成
- 個人設定 → API 設定 → **API Token 発行**（後で使う）
- テスト用に `/manuals/...` 配下へ数ページ手で作る or 登録 Bot で作る

### 2. Dify を起動（公式 self-host compose）

Dify 公式の docker compose を本番と同じバージョンで起動する（別ディレクトリで可）。
起動後:
- モデルプロバイダーに Anthropic / 埋め込み / Rerank を設定
- ナレッジ `manuals-local` を作成（Phase 1a と同じ設定）
- 質問 Bot（phase1a）と登録 Bot（phase1c）をインポート/構築

> Dify 本体はこのリポジトリに含めない（公式 compose を使う）。
> バージョンだけ本番に合わせる。

### 3. 本リポジトリのサービスを起動

```bash
cd ../services
cp docstore-growi/.env.example docstore-growi/.env
cp sync/.env.example          sync/.env
```

`.env` をローカル用に設定:

docstore-growi/.env:
```
GROWI_BASE_URL=http://host.docker.internal:3000
GROWI_API_TOKEN=<手順1で発行したトークン>
```

sync/.env:
```
DOCSTORE_URL=http://docstore-growi:8001        # compose 内部DNS（上書きされる）
DIFY_API_BASE_URL=http://host.docker.internal:5001
DIFY_API_KEY=<Dify ナレッジ API キー>
DIFY_DATASET_ID=<manuals-local の Dataset ID>
```

起動:
```bash
docker compose up -d --build
curl http://localhost:8002/health   # docstore/dify とも reachable:true が目標
```

### 4. 登録 Bot の HTTP Request ノードの URL

Dify の登録 Bot（phase1c）の HTTP Request ノードの URL を、
ローカルの adapter に向ける:
```
http://host.docker.internal:8001/pages
```

---

## 一気通貫テスト

[../dify/workflows/phase1c-setup.md](../dify/workflows/phase1c-setup.md) の runbook と同じ:

```
① 登録Bot にファイル投入 → GROWI に下書き
② GROWI で確認・公開
③ sync 実行: curl -X POST http://localhost:8002/sync -d '{"mode":"full"}' -H 'Content-Type: application/json'
④ 質問Bot で確認
```

全部この PC で完結する。コケたら各サービスのログ（`services/*/logs/`）を直接見られる。

---

## リソース目安

- Dify 一式 + GROWI（ES なし）+ mongo + 本サービス 2 つ
- RAM 8〜10GB 程度を想定。重い場合は Dify の sandbox / 未使用コンテナを止める

## 本番との差分（残るもの）

- ローカルとバージョンを合わせれば API 形状差はほぼ消える
- それでも最終確認は会社端末で 1 回行う（ネットワーク・実データ・本番設定の確認）
- 診断バンドル（diagnostics/collect.sh）はその最終確認用に引き続き有効
