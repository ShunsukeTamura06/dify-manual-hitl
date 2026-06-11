# 重複排除 提案フロー（HITL: 提案→承認→実行）

カオスなマニュアル群に散らばった重複を、**統合案を提示し人の承認を得てから**1 事実 1 ページに
収束させるための部品。設計の全体像は [docs/dedup-design.md](../../docs/dedup-design.md)。

## このディレクトリの中身（最小スコープ＝決定的コア）

```
dedup/clustering.py   # 候補ペア→クラスタ化(union-find)→重なり統計(difflib)→確信度→提案組立
tests/                # ローカル単体テスト（文書非依存・複数パターン）
```

`clustering.py` は**標準ライブラリのみ**で完結し、`main(pages, pairs)` をそのまま Dify の
Code ノードに貼れる。同じファイルをローカルで `pytest` にかけるのでロジックのドリフトが起きない
（[bulk-import](../bulk-import/) のスプリッターと同じ作り）。

## 役割分担

| 工程 | 実体 |
|------|------|
| 類似候補ペアの取得（意味検索） | Dify Knowledge Retrieval（登録 Bot の類似検索を再利用） |
| **クラスタ化・確信度・提案組立** | **本コア（Code ノード）** |
| 統合本文の生成（事実保持・矛盾注記） | LLM ノード（承認後） |
| 統合の確定（作成・退役） | DocStore Adapter（HTTP） |
| 承認 | チャットの対話ターン |

## ローカル検証

```bash
cd dify/dedup
uv run pytest
uv run ruff check dedup
uv run mypy dedup
```

## 確信度と承認負荷

- `confidence="high"`（重なり ≥ 0.8 かつタイトル一致）→ `lane="bulk"`：明白な重複として**一括承認**。
- それ以外 → `lane="individual"`：曖昧・矛盾の疑いとして**1 件ずつ承認**。

承認負荷を抑え、人の判断を本当に必要な数件に絞るための振り分け。閾値 `HIGH_OVERLAP` で調整。

## 実装状態

- ✅ 決定的コア（クラスタリング・確信度・提案組立）＋単体テスト。
- ⬜ Dify 配線（Knowledge Retrieval→Code→対話承認→LLM 統合→Adapter upsert/退役）と実機検証。
- ⬜ 統合本文生成プロンプト（欠落ゼロ・矛盾注記）と完全性チェック。
