# Dify Workflows

Dify Chatflow / Workflow の DSL (YAML) 定義置き場。

## Phase 1a: マニュアル質問 Bot

ファイル: [phase1a-qa-bot.yml](phase1a-qa-bot.yml)

### セットアップ手順

#### Step 1: ナレッジを作成

Dify Web UI で:

1. 「ナレッジ」→「ナレッジを作成」
2. 設定:

   | 項目 | 推奨値 |
   |------|--------|
   | 名前 | `manuals-phase1a` |
   | インデックス方法 | **高品質 (High Quality)** |
   | Embedding Model | **bge-m3** または **multilingual-e5-large** (日本語強)。OpenAI `text-embedding-3-large` も可 |
   | 検索設定 | **ハイブリッド検索 + Rerank** |
   | Reranker | **BAAI/bge-reranker-v2-m3** (セルフホスト) または **Cohere Rerank** |
   | チャンキング | **親子チャンク (Parent-Child)** ※Dify 0.7 以降 |
   | 親チャンク | 1024 トークン、区切り `\n\n` |
   | 子チャンク | 256 トークン、区切り `\n` |

   ※「親子チャンク」が無いバージョンの場合: 通常チャンク (1024 トークン、overlap 100) で代替。

3. **作成後、URL から Dataset ID を控える** (例: `https://dify.../datasets/<DATASET_ID>/documents`)

#### Step 2: マニュアルをアップロード

「ドキュメント」→「追加」で Word/Excel/PDF を 5-10 本投入。

**Phase 1a の目的は「品質測定」**なので、敢えて整形しないでそのまま入れる。整形しないと痛いことが分かるのが収穫。

インデックス完了まで数分〜数十分待つ。

#### Step 3: モデルプロバイダー設定

「設定」→「モデルプロバイダー」で以下を有効化:

| プロバイダー | モデル | 用途 |
|---|---|---|
| Anthropic | claude-sonnet-4-5（または最新版） | LLM |
| Hugging Face / OpenAI / Cohere | embedding model | ベクトル化（Step 1 で選んだもの） |
| Hugging Face / Cohere | reranker | 再ランク |

#### Step 4: Chatflow をインポート

1. 「スタジオ」→「アプリを作成」→「DSL からインポート」
2. [phase1a-qa-bot.yml](phase1a-qa-bot.yml) をアップロード
3. インポート後、以下 3 箇所を**必ず**修正:

   | 場所 | 置換内容 |
   |------|----------|
   | `knowledge_retrieval` ノードの `dataset_ids` | `REPLACE_WITH_YOUR_DATASET_ID` → Step 1 の Dataset ID |
   | `knowledge_retrieval` ノードの `reranking_model.provider` | 実際のプロバイダー名 (例: `huggingface_hub`) |
   | `knowledge_retrieval` ノードの `reranking_model.model` | 実際のモデル名 (例: `BAAI/bge-reranker-v2-m3`) |
   | `llm` ノードの `model.name` | 利用可能な Claude モデル名（バージョンの確認） |

4. 「公開する」→ プレビュー URL でテスト

#### Step 5: 実地テスト（20 件質問）

チームメンバー 2-3 人を巻き込んで、現実の質問を 20 件ぶつける:

- 自分が直近で困った質問
- 新人がよくする質問
- マニュアルに書いてあるはず系
- マニュアルに書いていない系（「該当なし」と返すか）
- 複数マニュアルにまたがる系

質問と回答をスプレッドシートに記録。

#### Step 6: 評価

20 件を以下で採点。詳細は [../../docs/phase-plan.md](../../docs/phase-plan.md) 参照。

| 観点 | 配点 |
|------|------|
| 正確性 | ◎/○/△/× |
| 完全性 | ◎/○/△/× |
| 出典妥当性 | ◎/○/△/× |
| 「該当なし」判定 | ◎/× |
| 応答速度 | 秒 |

**意思決定:**
- ◎○ が 70%+ → Phase 1b へ
- 50-70% → コンテンツ整備を先に
- 50% 未満 → アーキテクチャ見直し

---

### トラブルシュート

#### YAML インポートでエラーが出る
Dify のバージョン差で DSL 構造が違うことがある。対処:
1. 空の Chatflow を UI で新規作成
2. 同じノード構成 (Start → Knowledge Retrieval → LLM → Answer) を手動で組む
3. プロンプトと設定値は YAML から手でコピー

#### 「該当なし」と言うべき場面で憶測回答する
- `score_threshold` を上げる (0.3 → 0.5)
- LLM プロンプトの厳守ルール 1, 2 を強調

#### 同じ質問で違う回答が返る
- temperature を 0 にする
- Reranker が有効か確認
- top_k を下げる (10 → 5)

#### 応答が遅い
- Reranker を Cohere → FlashRank に変更（CPU 軽量）
- LLM を Haiku 系に変更
- top_k を下げる
