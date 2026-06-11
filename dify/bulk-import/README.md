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
- ⬜ Dify Chatflow への組み込み（実機 = 会社端末で検証）
- ⬜ 5 種類以上の実文書での一気通貫検証（欠落なし・適切分割の確認）
