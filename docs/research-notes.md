# ベストプラクティス調査メモ

設計判断の根拠となった、世界の事例・論文・記事の要点まとめ。

## 採用した主要パターン

### LLM Wiki Pattern (Karpathy)
- 原典: [karpathy/llm-wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
- 3 層構造: Raw Sources → Ingest Pipeline → Wiki Layer
- Wiki は RAG を**置き換えない**。両方使う
- 弱点: 情報損失・非決定性・誤りの凍結 → HITL とライフサイクル管理で対処
- 解説: [SmartScope: LLM Wiki Architecture](https://smartscope.blog/en/blog/llm-wiki-context-architecture/)
- 拡張: [LLM Wiki v2 (rohitg00 gist)](https://gist.github.com/rohitg00/2067ab416f7bbe447c1977edaaa681e2)

### Diátaxis Framework
- 公式: [diataxis.fr](https://diataxis.fr/)
- 4 分類: Tutorial / How-to / Reference / Explanation
- LangChain, Django, Cloudflare, NumPy 採用
- RAG との相性が良い（質問タイプ別に検索対象を絞れる）

### DITA (Topic-Based Authoring)
- IBM 発の 20 年以上の業界標準
- 1 トピック 1 ファイル + 参照で再利用（DRY for docs）
- 3 分類: Concept / Task / Reference

## RAG 技術スタックの定着パターン (2025-2026)

### Parent-Child Chunking
- 2026 production standard
- 子 128-256 トークン（検索精度）+ 親 512-1024 トークン（文脈）
- 出典: [Firecrawl: Best Chunking Strategies for RAG 2026](https://www.firecrawl.dev/blog/best-chunking-strategies-rag), [Weaviate: Chunking Strategies](https://weaviate.io/blog/chunking-strategies-for-rag)

### Hybrid Search + Reranking
- Vector + BM25 を fusion → Reranker で再順位付け
- Reranker 候補:
  - **bge-reranker-v2-m3** (BAAI): セルフホスト、無料、精度高
  - **Cohere Rerank v3.5**: マネージド、API
  - **FlashRank**: CPU 軽量 (15-30ms)
- 精度は近い、差別化は運用モデルで決まる
- 出典: [Reranking in RAG: Cohere/BGE/FlashRank](https://medium.com/@vaibhav-p-dixit/reranking-in-rag-cross-encoders-cohere-rerank-flashrank-c7d40c685f6a), [Superlinked VectorHub](https://superlinked.com/vectorhub/articles/optimizing-rag-with-hybrid-search-reranking)

### ライティング規約 (AWS Prescriptive Guidance)
- [AWS: Documentation best practices for RAG applications](https://docs.aws.amazon.com/prescriptive-guidance/latest/writing-best-practices-rag/best-practices.html)
- 主要ポイント:
  - 見出し直下に要約 1-2 文 → 意味的カバレッジ向上
  - テーブルを避ける → フラット箇条書きへ
  - 番号付きリストは連番厳守、項目間に接続詞
  - 略語・社内用語を必ず定義
  - 大きなドキュメントは分割
- **現場適用での修正**: 「テーブルを避ける」は当プロジェクトでは撤回。
  現場は Excel 由来で表が多く、表の維持が必須。代わりに「表は残し、直前に
  検索用の平文を併記（登録 Bot が自動生成）」に変更（conventions/writing-style.md）。

## 重複・矛盾・非決定性の研究

- [arXiv: On the Reproducibility Limitations of RAG Systems](https://arxiv.org/pdf/2509.18869)
  - 同じクエリで異なる結果が返るのは RAG の構造的問題
- [arXiv: Improving Consistency in RAG with Group Similarity Rewards](https://arxiv.org/pdf/2510.04392)
  - 一貫性向上の学習手法
- 実務的対処:
  - temperature を下げる (0-0.1)
  - メタデータ駆動の優先順位付け (canonical, updated_at)
  - 矛盾検出をプロンプトで義務化

## ライフサイクル管理の重要性

> "An LLM wiki that goes stale becomes actively harmful — it provides confident-sounding answers based on outdated information."
> ([Beyond RAG: Karpathy's LLM Wiki Pattern](https://levelup.gitconnected.com/beyond-rag-how-andrej-karpathys-llm-wiki-pattern-builds-knowledge-that-actually-compounds-31a08528665e))

→ 古さ対策は必須。ただし**手段**は現場で修正した。
  当初は owner / review_due / orphan 検知（人手の棚卸し）を想定したが、
  現場では owner / review_due を運用で埋められないと判明。
  → 人手棚卸しに依存せず、「最終更新日（自動）からの経過 + 回答時の更新日表示・
  古さ警告」で代替する方針に変更（docs/architecture.md「品質と鮮度の担保」）。

## HITL の位置づけ (2025-2026)

- 2025 年が「エージェントの年」と呼ばれた反動で、人間検証が再注目
- [Technology.org: AI Still Needs Humans](https://www.technology.org/2025/10/20/ai-still-needs-humans-why-human-in-the-loop-teams-matter-in-the-llm-era/)
- パターン: AI が提案 → 人が承認 (Red Hat の例: code diff → docs PR、マージは人間)
- 出典: [Red Hat: AI-Powered Documentation Updates](https://developers.redhat.com/articles/2026/04/21/ai-powered-documentation-updates-code-diff-docs-pr-one-comment)

## 競合プロダクト（参考）

エンタープライズ KM AI チャットボット製品が増加。マルチソース統合（Notion + Confluence + Drive + Slack）が標準化。

- Langdock, eesel AI, ravenna, MindStudio, Question Base
- Mintlify (docs-as-code + AI native, Anthropic/Coinbase/Cursor/Vercel/Zapier 採用)

セルフホスト・コントロール重視なら自作 (Dify ベース) のメリットが残る。

## 我々の設計との照合

| 設計判断 | 業界標準 | 整合性 |
|----------|----------|--------|
| Wiki = SoT, RAG = derived | LLM Wiki Pattern | ✅ |
| Wiki 実装の抽象化 | (一般的なソフトウェア原則) | ✅ |
| Diátaxis 4 分類 | de facto standard | ✅ |
| Parent-Child Chunking | 2026 production standard | ✅ |
| Hybrid + Rerank | 普遍的合意 | ✅ |
| HITL = 自己承認 (Wiki 上で公開) | Red Hat パターンと同型 | ✅ |
| owner / review_due | Karpathy 弱点への明示的対処 | ✅ |
| 生ソースも保持 | Karpathy が推奨 | ✅ |
| temperature 0.1 | 一貫性研究の知見 | ✅ |

→ 我々の設計は世界の主流と一致している。後追いだが正しい方向。
