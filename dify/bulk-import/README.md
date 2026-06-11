# 一括取り込み Bot（大規模文書スプリッター・案A Map-Reduce）

巨大なマニュアル（例: 80 ページの規程集）を、**内容を落とさず適切な単位で複数ページに
分割**して Wiki に取り込むための Dify アプリ。既存の「登録 Bot」（1 ファイル=1 ページ）
とは別アプリにする（[docs/splitter-design.md](../../docs/splitter-design.md) の方針）。

## 背景（解く問題）

現行の登録 Bot は 1 ファイルを 1 回の LLM 出力で整形するため、大きな文書では出力
トークン上限に収まらず**要約・圧縮**されてしまう（実測: 抽出 59,350 字 → 出力 5,143 字、
98% 脱落）。本アプリは Map-Reduce で「分割 → 各部を整形 → 継ぎ合わせ → 各ページ作成」と
することでこの欠落を防ぐ。

## このディレクトリの中身

```
splitter/
  windows.py   # ウィンドウ分割（Map 前段）。Dify Code ノードにそのまま貼れる
  reduce.py    # 継ぎ合わせ（Reduce）。Dify Code ノードにそのまま貼れる
prompts/
  window-extract.md   # Iteration 内の LLM（各ウィンドウの完結トピック抽出）プロンプト
tests/         # ローカル単体テスト（複数文書種で汎用性を検証）
```

`splitter/windows.py` と `splitter/reduce.py` は**標準ライブラリのみ**で完結しており、
それぞれの `main()` 関数を Dify の Code ノードにコピペして使う。同じファイルをローカルで
`pytest` にかけるので、ロジックのドリフトが起きない。

## ローカル検証（このPCで完結する部分）

```bash
cd dify/bulk-import
uv run pytest          # ウィンドウ分割・継ぎ合わせの単体テスト
uv run ruff check .
uv run mypy splitter
```

文書非依存であることを担保するため、テストは手順書 / 規程 / FAQ / 表主体 / 箇条書き主体の
5 種類（[tests/fixtures.py](tests/fixtures.py)）で「内容欠落なし・適切に複数分割」を確認する。

## Dify フロー（案A）

```
[Start: file + 補足]
  → [Document Extractor]
  → [Code: split_windows]        ← splitter/windows.py の main を貼る
       入力: text = {{#document_extractor.text#}}
       出力: windows (Array[String])
  → [Iteration: windows を反復]
       └ [LLM: 各ウィンドウの完結トピックを JSON 配列で抽出]
            system プロンプト: prompts/window-extract.md
            出力: 各ウィンドウの JSON 文字列
  → [Code: merge_pages]          ← splitter/reduce.py の main を貼る
       入力: window_results = Iteration の出力（Array[String]）
       出力: pages (Array[Object]) = [{title, content}, ...]
  → [Iteration: pages を反復]
       └ [Parameter Extractor: path/title 抽出] → [Code: JSON 組立] → [HTTP: POST /pages (upsert)]
  → [Answer: 「N ページを作成しました」一覧]
```

- upsert・JSON 組立・HTTP の各ノードは既存登録 Bot
  （[dify/workflows/phase1c-setup.md](../workflows/phase1c-setup.md)）の Step 6〜8 を流用する。
- 環境変数 `DOCSTORE_URL` 等の扱いも既存 Bot に合わせる（ハードコードしない）。

## 汎用性の制約（厳守）

[docs/splitter-design.md](../../docs/splitter-design.md) の「汎用性の制約」を厳守する。

- 特定マーカー（「事例N」「第N章」等）をハードコードしない。分割は段落 → 行 → 文字の
  機械的フォールバックのみ（`windows.py`）。意味単位の判断は LLM に委ねる。
- プロンプトもドメイン用語に依存させない（「トピック/タスクの完結単位で分ける」一般指示）。

## 実装状態

- ✅ ウィンドウ分割・継ぎ合わせロジック（ローカル単体テスト済み・文書非依存）
- ✅ Iteration 内 LLM プロンプト（汎用）
- ✅ Dify Chatflow（[../workflows/bulk-import-bot.yml](../workflows/bulk-import-bot.yml)）— ローカル
  Dify 1.9.2 にインポートし、実 GROWI へ一気通貫で複数ページ作成を確認（下記）。
- ⬜ 複数種類（規程/FAQ/表主体/箇条書き）の実文書での追試、会社端末での最終確認。

## 実機検証で分かったこと（ローカル Dify 1.9.2 + gpt-4o-mini + GROWI 7.4.2）

13K 字・8 トピックの手順書を投入し、2 ウィンドウ → 8 ページを GROWI に作成（8/8 成功、
境界を跨ぐトピックの手順 12/12 ステップ保持、合計本文 11K 字。元バグの 98% 圧縮は解消）。
ここに至るまでに実データで判明した、設計に反映済みの重要点：

1. **gpt-4o-mini は過剰分割する**。素のプロンプトでは番号付きステップを 1 つずつ別ページに
   割り（1 ウィンドウで 53 分割）、Dify の Code 出力上限（後述）にも抵触した。
   → プロンプトで「手順のステップは分割しない／1 ウィンドウ 1〜6 トピック目安」を強く明示し解消。
2. **gpt-4o-mini は境界フラグ（continues_previous / incomplete）を立てない**。このため
   ウィンドウ境界を跨ぐトピックが「見出しだけのページ＋本体ページ」に割れ、同名＝同一パスで
   衝突し本体が 409 で失われた。
   → 継ぎ合わせ（[splitter/reduce.py](splitter/reduce.py)）に **境界でタイトル一致なら結合**する
   フラグ非依存のフォールバックを追加（文書非依存）。
3. **Dify Code ノードの配列出力は既定で 30 要素まで**（`CODE_MAX_STRING_ARRAY_LENGTH` /
   `CODE_MAX_OBJECT_ARRAY_LENGTH`）。31 ページ超の文書を扱うには Dify 側でこの環境変数を
   引き上げる必要がある（デプロイ要件。会社端末でも設定する）。
4. **Iteration の並列実行で Code サンドボックスが `operation not permitted` を散発**し、
   `continue-on-error` と相まってページが 1 枚黙って欠落した。
   → 内容欠落を最優先で防ぐため **両 Iteration を逐次実行（is_parallel: false）** にした
   （その分遅いが、巨大文書のバッチ取り込みでは許容）。さらに集計ノードで
   「作成数 / 期待ページ数」を突き合わせ、欠落が起きた場合は回答に明示する。

> 再取り込み時の冪等性: 現状は同一パスが既存だと 409。継ぎ合わせ修正で同名衝突は解消したが、
> 同じ文書を再投入すると既存ページに 409 が出る（`continue-on-error` でスキップ）。
> パス指定 upsert はアダプタ側の今後の拡張候補。
