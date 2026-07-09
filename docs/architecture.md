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
| Obsidian で個人/チーム管理している | Obsidian Vault Adapter (= Filesystem 系) |
| 何も無い / 技術寄り | **Git + Markdown + MkDocs**（推奨デフォルト） |
| 非技術者のみ・最低限 | 共有フォルダ + Markdown（妥協） |

### Adapter 実装一覧（交換可能な部品）

GROWI は「DocStore 契約を満たす実装の 1 つ」にすぎない。
契約 ([contracts/docstore-openapi.yaml](../contracts/docstore-openapi.yaml)) さえ満たせば、
中身が何であれ呼び出し側（Sync Service / 登録 Bot）からは同じに見える。

| Adapter | `create_page` の実体 | `viewer_url` の形式 | 状態 |
|---------|---------------------|---------------------|------|
| **GROWI** | GROWI API で POST | `https://growi.../path` | ✅ 実装済 |
| **Filesystem / Git** | `.md` を書く + `git commit` | MkDocs 等の公開サイト URL | ⚪ Phase 3 |
| **Obsidian Vault** | Vault フォルダに `.md` を書く | `obsidian://open?vault=...&file=...` | ⚪ Phase 3 |
| **Confluence** | Confluence REST API で作成 | `https://confluence.../pages/123` | ⚪ 必要時 |
| **Notion** | Notion API でページ作成 | `https://notion.so/...` | ⚪ 必要時 |

**契約は同じ、翻訳だけが違う。** 各 Adapter は「Wiki 固有形式 ↔ DocStore モデル」の変換に徹する。

補足:
- **Filesystem / Git と Obsidian Vault はほぼ同一実装**になる（どちらも「フォルダ内の `.md`
  を読み書き」）。違いは `viewer_url` の形式程度。1 つの `docstore-filesystem` で
  設定により両対応できる見込み。
- **契約の限界（トレードオフ）**: Adapter パターンは「最大公約数的な機能」しか扱えない。
  Markdown 本文 + メタデータ + 履歴までが契約の範囲。各 Wiki の尖った機能
  （GROWI のページ権限、Confluence のマクロ、Notion の DB ビュー、Obsidian のグラフ
  ビュー等）は契約に含めない。マニュアル管理用途ではこの最大公約数で十分カバーできる。
  必要になれば契約を拡張する（ルール 5: スキーマバージョニングに従う）。

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
title: 国内出張の経費を精算する
type: howto | tutorial | reference | explanation
status: published | draft | deprecated
# 以下は任意（埋められる人だけ。空でよい）
audience: 全社 | 経理部 | マネージャー
canonical: false             # この事実の正典なら true
related: ["/manuals/..."]    # 関連ページ
owner:                       # 任意（運用で埋まらない前提）
review_due:                  # 任意（運用で埋まらない前提）
---
```

**重要（現場フィードバック反映）**: 当初 `owner` / `review_due` を
ライフサイクル管理の肝としていたが、現場では運用で埋められないことが判明。
→ これらは**任意**とし、古さの管理は人手の棚卸しに依存しない方式に変更（下記）。

## 品質と鮮度の担保（読込時に移動）

「誰も完全な正解を知らない」「メタデータを人手で維持できない」現場の実態を踏まえ、
品質担保を **書込時のゲートから読込時の透明性 + 自動シグナル**に移す。

| やめたこと（書込時・人手依存） | 置き換え（読込時・自動） |
|---|---|
| owner / review_due で棚卸し | **最終更新日（GROWI 自動）からの経過**で古さを判定 |
| 承認ゲートで正しさを保証 | 回答に**出典 URL + 更新日**を必須表示、使う人が原典で確認 |
| 重複を判定してブロック | 重複は**提示のみ**。読込時の矛盾検出で表面化させ継続的に収束 |
| 期限通知バッチ | 一定期間未更新ページを回答時に「最新か確認を」と**注記**（✅ 実装済み。[phase1c-design.md](phase1c-design.md) の品質担保表参照） |

## 重複・矛盾の対策（多層防御・改訂）

| 層 | 対策 |
|----|------|
| 設計 | 1事実1ページ。他からはリンクで参照（DRY for docs）。ただし完璧は求めない |
| 登録時 | 類似ページを**提示するだけ**（ブロックしない） |
| 検索 | Rerank + Hybrid Search + メタデータブースト |
| 回答 | 矛盾検出を必須化、**出典 URL + 更新日**を必須、古さを注記 |
| 継続 | 「この回答は違った」フィードバックでページ修正（人手棚卸しに依存しない） |

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
- **表は残す + 直前に検索用の平文を併記**（現場は Excel 由来で表が多い。
  当初の「表を避ける」案は実態に合わず撤回。平文は登録 Bot が自動生成）
- 番号付きリストは連番厳守、項目間に接続詞
- 略語・社内用語を必ず定義
- 大きなドキュメントは小さく分割
- 画像にテキスト記述を併記

→ 詳細は [conventions/writing-style.md](../conventions/writing-style.md)。
ページ構造の標準形は [conventions/manual-template.md](../conventions/manual-template.md)。

## 参考文献

ベストプラクティス調査結果は [research-notes.md](research-notes.md) を参照。
