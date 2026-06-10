# Phase 1c: 登録 Bot セットアップ & 一気通貫テスト

ファイルをアップロード → LLM が整形 → GROWI に下書き作成、までの Chatflow。
LLM は Dify 経由（プロキシ制約のため Claude 直叩きはしない）。
GROWI 書き込みは docstore-growi アダプタの `POST /pages` を HTTP Request ノードで叩く。

> **推奨は YAML インポート**（[phase1c-registration-bot.yml](phase1c-registration-bot.yml)）。
> Dify 1.9.2 で「スタジオ → アプリ作成 → DSL からインポート」→ 起動まで実機検証済み
> （1.9.2 必須フィールドは YAML に反映済み）。インポート後に LLM のモデルを環境に合わせて
> 選び直し（OpenAI なら gpt-4o-mini 等）、environment_variables の DOCSTORE_URL を確認すればよい。
>
> 以下は UI から手組みする場合の手順（各ノードの設定値・スクリプトのリファレンスも兼ねる）。

---

## 前提

- Phase 1a のナレッジ（`manuals-phase1a` 等）が作成済み
- docstore-growi / sync が起動済み（`services/docker-compose.yml`）
- Dify から docstore-growi に到達できること
  - 同一ホストなら `http://host.docker.internal:8001` 等
  - URL は後の HTTP Request ノードで使う

---

## ノード構成

```
[Start: file + 補足]
  → [Document Extractor]
  → [LLM-1: 整形]
  → [Parameter Extractor: path/title/type 抽出]
  → [Code: JSON ボディ組立（json.dumps で安全に）]
  → [HTTP Request: POST /pages]
  → [Answer: GROWI URL を返す]
```

---

## Step 1: アプリ作成

「スタジオ」→「アプリを作成」→「最初から作成」→ **Chatflow** を選択。
名前: `マニュアル登録Bot`。

---

## Step 2: Start ノード（ファイルアップロード）

- 「機能」→ **ファイルアップロード** を ON。
  - 種類: ドキュメント（Word/Excel/PDF/テキスト）
  - 上限: 1 ファイル（まずは単一で検証）
- これでチャット欄からファイルを添付できる。
- ユーザーのチャット文（補足説明）は `sys.query` で参照する。

---

## Step 3: Document Extractor ノード

- 入力変数: Start の **アップロードファイル**（`sys.files` の先頭、または file 変数）
- 出力: 抽出テキスト（以後 `{{#doc_extractor.text#}}` と表記）

> Word/Excel/PDF の抽出はここが担う。抽出品質はこのノードの出力で確認できる。

---

## Step 4: LLM-1 ノード（整形）

- モデル: Anthropic Claude（Dify に設定済みのもの）
- temperature: 0.2
- system プロンプト: [prompts/llm1-format.md](prompts/llm1-format.md) の system プロンプトを貼る
  - frontmatter に **path も出す**よう更新済み
- user プロンプト:
  ```
  # 元のマニュアル素材
  {{#doc_extractor.text#}}

  # ユーザーからの補足
  {{#sys.query#}}
  ```
- 出力: 整形済み Markdown（`{{#llm1.text#}}`）

---

## Step 5: Parameter Extractor ノード

LLM-1 が出した Markdown の frontmatter から、登録に必要な項目を構造化抽出する。

- 入力: `{{#llm1.text#}}`
- 抽出パラメータ:
  | 名前 | 型 | 説明 |
  |------|----|------|
  | `path` | string | frontmatter の path（GROWI 配置パス） |
  | `title` | string | frontmatter の title |
  | `type` | string | frontmatter の type |
- 指示文（例）:
  ```
  与えられた Markdown の frontmatter から path, title, type を抽出してください。
  値が無い場合は空文字にしてください。
  ```

---

## Step 6: Code ノード（JSON ボディを安全に組む）

HTTP の JSON ボディに Markdown を直接埋めると改行・引用符で壊れる。
Code ノードで `json.dumps` して 1 つの文字列にする。

- 入力変数:
  - `path` ← `{{#parameter_extractor.path#}}`
  - `title` ← `{{#parameter_extractor.title#}}`
  - `type_` ← `{{#parameter_extractor.type#}}`
  - `content` ← `{{#llm1.text#}}`
- コード（Python3）:
  ```python
  import json

  def main(path: str, title: str, type_: str, content: str) -> dict:
      # content には LLM-1 が作った frontmatter（status: draft 等）が既に含まれる。
      # metadata を別送すると frontmatter が二重になるため、metadata は空にし、
      # content の frontmatter を正とする（アダプタは読み出し時に frontmatter を
      # metadata に復元するので往復が一致する）。
      body = json.dumps(
          {
              "path": path,
              "title": title,
              "content": content,
              "metadata": {},
          },
          ensure_ascii=False,
      )
      return {"body": body}
  ```
- 出力: `body`（string）
- 補足: `type_` は将来 metadata を使う場合のために受け取っているが、現状は未使用でよい。

---

## Step 7: HTTP Request ノード（GROWI に下書き作成）

- メソッド: **POST**
- URL: `http://host.docker.internal:8001/pages`
  （docstore-growi の到達 URL に合わせる。docker network 参加なら `http://docstore-growi:8001/pages`）
- ヘッダ: `Content-Type: application/json`
- ボディ: **raw / text** を選び、中身に `{{#code.body#}}` を入れる
  （JSON タイプではなく raw にするのがポイント。Code が整形済みの JSON 文字列を渡す）
- 出力: レスポンス本文 `{{#http_request.body#}}`、ステータス `{{#http_request.status_code#}}`

---

## Step 8: Answer ノード

- 内容（例）:
  ```
  GROWI に下書きを作成しました（status: draft）。

  内容を確認し、問題なければ GROWI で「公開」してください。
  公開すると次回同期で検索（質問Bot）に反映されます。

  レスポンス: {{#http_request.body#}}
  ```

> レスポンス本文に viewer_url が含まれる（docstore-growi が返す Page.viewer_url）。
> 余裕があれば Code ノードでパースして URL だけ綺麗に出してもよい。

---

## Step 9: 公開

右上「公開する」→ プレビューでチャットを開く。

---

## 一気通貫テスト（runbook）

会社端末で、登録 → 公開 → 同期 → 質問 の全経路を通す。

```
① 登録Bot でファイル投入
   チャットにマニュアル（Word/Excel）を添付 + 「経費精算のマニュアルです」等の補足
   → 「GROWI に下書きを作成しました」と URL が返る

② GROWI で確認・公開
   返ってきた URL を開く
   → frontmatter・本文・表が整形されているか確認
   → status を published にして公開（または下書きを公開操作）

③ 同期を実行
   curl -X POST http://localhost:8002/sync \
     -H 'Content-Type: application/json' -d '{"mode":"full"}'
   → created/updated の件数を確認

④ 質問Bot で確認
   Phase 1a の質問Bot で、今登録した内容を質問
   → GROWI の URL 付きで回答が返る

⑤ 診断バンドル（うまくいかない場合）
   bash diagnostics/collect.sh
   → bundle-*.zip を持ち帰る
```

### 各段でコケたときの切り分け

| 症状 | 見るところ |
|------|-----------|
| ①でファイル抽出が変 | Document Extractor の出力。Word/Excel の抽出品質 |
| ①で整形が崩れる | LLM-1 の出力（特に表・frontmatter） |
| ①で GROWI 作成が 4xx/5xx | HTTP Request の URL・ボディ、docstore-growi のログ |
| ②で表示が崩れる | LLM-1 の Markdown、GROWI のレンダリング |
| ③で同期されない | sync の dry-run、status フィルタ、docstore /pages の応答 |
| ④で出てこない | Dify Knowledge にドキュメントが入ったか、再インデックス待ち |

---

## 既知の留意点

- **status フィルタ**: 現状 sync は status を見ず全ページ同期する。draft を除外したい場合は
  sync 側に status フィルタ追加が必要（[docs/phase1c-design.md](../../docs/phase1c-design.md) 参照）。
  まず一気通貫を通すなら、テストでは公開（published）まで進めれば問題ない。
- **重複の提示**: 軽量版では重複チェック（Knowledge Retrieval での気づき）は省いている。
  まず登録→同期→質問の幹を通すことを優先。必要なら後で Retrieval ノードを挿す。
- **HTTP 到達**: Dify と docstore-growi のネットワーク疎通が最初の関門。
  Answer に出る HTTP ステータスでまず疎通を確認するとよい。
