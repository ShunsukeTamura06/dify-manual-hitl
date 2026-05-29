# アーキテクチャ

> このドキュメントは「何を作るか」を扱う。
> 「どう作るか／崩さないか」の原則は [design-principles.md](design-principles.md) を参照。

## 全体像

```
┌──────────────────────────────────────────────────────────┐
│  Wiki Layer = Single Source of Truth                     │
│  - 人間が閲覧・編集・承認する場所                          │
│  - バージョン履歴を保持                                    │
│  - 実装は差し替え可能 (GROWI / Git+MD / Confluence / ...) │
└──────────────────────────────────────────────────────────┘
       ↑ 整形・ドラフト投入             ↓ 同期 (派生)
┌──────────────────┐              ┌──────────────────┐
│ Dify 登録 Bot     │              │ Dify Knowledge   │
│ (Phase 1c)       │              │ (RAG インデックス) │
└──────────────────┘              └──────────────────┘
       ↑                                    ↓
   [ユーザー]                       ┌──────────────────┐
   アップロード                      │ Dify 質問 Bot     │
                                   │ (Phase 1a)       │
                                   └──────────────────┘
                                          ↑
                                      [ユーザー]
                                       自然言語質問
```

## なぜこの構成か

### LLM Wiki パターン (Karpathy)

Andrej Karpathy が提唱した「LLM Wiki」パターンを採用。

**従来の純粋 RAG との違い:**
- 純粋 RAG: クエリ時に都度合成
- LLM Wiki: 取り込み時に合成 → Wiki として永続化 → そこから検索

**メリット:**
- 繰り返し参照される知識を永続的な成果物として育てられる
- Wiki に蓄積されるので、人間も同じものを読める
- 検索対象が整理済みなので精度が安定

**リスク（必須の対策）:**
- 情報損失: 要約で詳細が落ちる → **生ソースも別データセットで保持**して原典遡及可能に
- 非決定性: LLM 生成 Wiki にブレ → **HITL 必須**
- 誤りの凍結: 一度間違った要約が後続クエリの根拠に → **定期見直し（review_due）必須**

### Wiki 実装は抽象化

Wiki 層は「DocStore Adapter」というインターフェース越しに使う。
チームごとの状況に応じて実装を差し替え。

| チームの状況 | 推奨実装 |
|---|---|
| 既に GROWI を使っている（当チーム） | GROWI Adapter |
| 既に Confluence を使っている | Confluence Adapter |
| 既に Notion を使っている | Notion Adapter |
| 何も無い / 技術寄り | **Git + Markdown + MkDocs**（推奨デフォルト） |
| 非技術者のみ・最低限 | 共有フォルダ + Markdown（妥協） |

### DocStore Adapter インターフェース（仕様メモ）

```python
class DocStore(ABC):
    def list_pages(self, path_prefix: str = "") -> list[PageMeta]: ...
    def get_page(self, page_id: str) -> Page: ...
    def create_page(self, path: str, content: str, metadata: dict) -> Page: ...
    def update_page(self, page_id: str, content: str, metadata: dict) -> Page: ...
    def delete_page(self, page_id: str): ...
    def get_viewer_url(self, page_id: str) -> str: ...
    def subscribe_changes(self, callback): ...

class Page:
    id: str
    path: str           # 例: /manuals/経理/経費精算/_howto/国内出張
    title: str
    content: str        # Markdown 本文
    metadata: dict      # type, owner, review_due, audience, canonical, ...
    version: str
    updated_at: datetime
    viewer_url: str     # 人間が開く URL
```

実装は `dify/adapters/` 配下に置く（Phase 1b 以降）。

## IA: Diátaxis 4 分類

ページパスに分類タグを含める：

```
/manuals/<部署>/<業務カテゴリ>/_<分類>/<タスク名>
```

| 分類 | 目的 | 例 |
|------|------|------|
| `_tutorial`  | 学習 | 経費精算を初めて使う人向け |
| `_howto`     | 作業遂行 | 海外出張の経費精算手順 |
| `_reference` | 仕様確認 | 経費科目一覧、上限額一覧 |
| `_explanation` | 理解 | 経費精算ポリシーの考え方 |

質問 Bot は質問タイプを判定して該当タイプを優先検索（Phase 2 以降の最適化）。

## ページメタデータ（YAML Frontmatter）

```yaml
---
type: howto | tutorial | reference | explanation
audience: 全社 | 経理部 | マネージャー
owner: tamura@example.com    # 責任者
review_due: 2026-12-31       # 見直し期限
related: ["/manuals/..."]    # 関連ページ
status: published | draft | deprecated
canonical: false             # この事実の正典なら true
---
```

`owner` と `review_due` が**ライフサイクル管理の肝**。

## 重複・矛盾の対策（多層防御）

| 層 | 対策 |
|----|------|
| 設計 | 1事実1ページ。他からはリンクで参照（DRY for docs） |
| 登録時 | 類似検索 → 重複候補を HITL で確認 |
| 検索 | Rerank + Hybrid Search + メタデータブースト |
| 回答 | LLM プロンプトで矛盾検出を必須化、出典 URL 必須 |
| 定期 | 類似ページ自動検知バッチ、orphan 検知、review_due 通知 |

## RAG 技術スタック（2026 standard）

### チャンキング: Parent-Child
- 親 1024 トークン（LLM 渡し用）
- 子 256 トークン（検索インデックス）

### 検索: Hybrid + Rerank
- 1段: ベクトル検索 + BM25
- 2段: Reranker で再順位付け
- Reranker 候補: bge-reranker-v2-m3（セルフホスト）/ Cohere Rerank / FlashRank

### 生成: Claude + 低 temperature
- temperature 0.1 で決定性確保
- 出典必須・「該当なし」明示・矛盾検出のプロンプト

## ライティング規約（AWS 推奨）

- 見出しと小見出しを階層的に使う
- **見出し直下に 1-2 文の要約**（チャンク化したときの意味的カバレッジ向上）
- **テーブルは使わずフラット箇条書きに**（LLM がテーブル構造を誤読しがち）
- 番号付きリストは連番厳守、項目間に接続詞
- 略語・社内用語を必ず定義
- 大きなドキュメントは小さく分割
- 画像にテキスト記述を併記

→ `conventions/writing-style.md` に転記（Phase 後半）

## 参考文献

ベストプラクティス調査結果は [research-notes.md](research-notes.md) を参照。
