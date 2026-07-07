# 実データ評価パック（Phase 1a ゲートを会社環境で閉じる）

このディレクトリは、**会社の実マニュアル・実質問で RAG 品質を評価する**ための一式。
[docs/phase-plan.md](../docs/phase-plan.md) の Phase 1a 評価ゲート
（20 問・◎○ 70% 以上で次フェーズ投資を判断）を、会社端末での **1 回の作業**で
実行し、結果を診断バンドルで持ち帰れるように作ってある。

スクリプトはすべて **Python 標準ライブラリのみ**で動く（会社プロキシ下で
pip / uv によるパッケージ取得が不要）。

## 事前準備（このPC / チームで）

1. **質問 20 問を用意する**: `questions.example.tsv` を参考に、実際に社員が聞きそうな
   質問を TSV で作る（S端末上で `evaluation/questions.tsv` として作成。リポジトリには
   コミットしない）。以下を必ず混ぜる:
   - マニュアルに答えがある質問（大半）
   - **答えが存在しない質問を 2〜3 問**（「該当なし」と言えるかの検証）
   - 複数マニュアルにまたがる質問・表の中の数値を問う質問
2. **実マニュアル 5〜10 本**を選んでおく（Word/Excel/PDF。表が多いもの・古いものを
   意図的に含めると実態に近い評価になる）
3. GitHub の main を最新化しておく（会社端末は pull のみ可能）

## 会社端末（S端末）での手順

### 0. 取得と起動

```bash
git clone <GitHub or 社内GitLab の URL> && cd dify-manual-hitl
# services の .env を作成（トークン類は現地で発行。DEPLOYMENT.md 参照）
cp services/docstore-growi/.env.example services/docstore-growi/.env
cp services/sync/.env.example          services/sync/.env
# 編集後:
cd services && docker compose up -d --build && cd ..
curl http://localhost:8002/health   # 両方 reachable:true を確認
```

- Dify / GROWI は社内の稼働環境を使う（バージョンはローカル検証と同じ
  Dify 1.9.2 / GROWI 7.4.2 が前提）。
- Dify UI でナレッジ（high_quality + 埋め込みモデル）を 1 つ作成し、
  **Dataset ID**（URL の `/datasets/<ID>/`）を控える。

### 1. Bot のインポート（プレースホルダをスクリプトで差し替え）

```bash
DIFY_BASE_URL=http://<difyのURL> DIFY_EMAIL=<管理者> DIFY_PASSWORD=<パスワード> \
DATASET_ID=<控えたID> \
MODEL_PROVIDER=<社内で使うLLMのprovider> MODEL_NAME=<モデル名> \
python evaluation/import_apps.py
```

- Reranker が無い環境はそのままで良い（既定で weighted_score に書き換える）。
  ある場合は `RERANKER=keep` にしてインポート後 UI で設定。
- 出力された app_id 一覧が `evaluation/out/app-ids.txt` に残る。

### 2. 実マニュアルの投入 → 公開 → 同期

実運用と同じ経路で入れる（パイプライン自体の検証を兼ねる）:

1. 登録 Bot（小さいファイル）/ 一括取り込み Bot（大きいファイル）に実マニュアルを投入
   → GROWI に下書きができる
2. GROWI で内容を確認し、frontmatter の `status: draft` を `published` に変更（=HITL承認）
3. 同期: `curl -X POST http://localhost:8002/sync -H 'Content-Type: application/json' -d '{"mode":"full"}'`
4. Dify のナレッジにドキュメントが入ったことを UI で確認

> 途中で失敗した場合も、そのまま手順 4 の collect.sh まで進めてバンドルを持ち帰る
> （生レスポンスが修正の材料になる。debug エンドポイントは
> `DEBUG_ENDPOINTS_ENABLED=true` で有効化）。

### 3. 評価の実行

```bash
DIFY_BASE_URL=http://<difyのURL> DIFY_EMAIL=<管理者> DIFY_PASSWORD=<パスワード> \
EVAL_APP_ID=<qa の app_id> \
python evaluation/run_eval.py evaluation/questions.tsv
```

- `evaluation/out/eval-<日時>/report.md` に採点表が出る。
- **その場でチームで ◎○△× を記入**する（回答全文と引用が同じファイルにある）。
  記入もその場で終わらせると持ち帰りが 1 回で済む。

### 4. 持ち帰り

```bash
bash diagnostics/collect.sh   # evaluation/out/ もバンドルに含まれる
```

zip を申請してこの PC へ。結果を見て phase-plan の意思決定
（70% ルール）を行う。

## 判定後の分岐（phase-plan より）

| 結果 | 次の一手 |
|------|---------|
| ◎○ 70% 以上 | 本採用に向けた展開へ（承認運用の整備・Phase 2） |
| 50〜70% | コンテンツ整備を先に（IA 規約・ライティング規約の適用、整形プロンプト改善） |
| 50% 未満 | アーキテクチャ見直し（Vision LLM 前処理の繰り上げ等） |

## 注意

- `questions.tsv`（実質問）と `out/`（実データを含む結果）は **コミットしない**
  （.gitignore 済み）。持ち出しはバンドル申請の手続きに従う。
- パスワード等のシークレットはコマンドの環境変数でのみ渡し、出力ファイルには残らない。
