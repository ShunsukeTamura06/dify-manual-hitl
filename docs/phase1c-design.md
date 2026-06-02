# Phase 1c 設計: 登録 Bot

ユーザーがアップロードしたファイルを、LLM が整形し、重複を確認し、
Wiki にドラフトとして登録するまでを担う。

HITL（人間確認）は **Wiki 上での編集・公開** で担保する（Dify 内では完結させない）。

> 状態: 設計フェーズ。1b（同期）の実機検証と並行して準備中。
> 実 API 形状に依存する部分（GROWI 書込・Dify 検索の実挙動）は 1b 検証後に確定する。

---

## フロー全体

```
[Start: ファイル添付 + 補足説明]
   ↓
[Document Extractor] ファイル → テキスト
   ↓
[LLM-1: 標準テンプレートに整形]
   conventions/manual-template.md + writing-style.md に従う
   出力: 整形済み Markdown（frontmatter 込み）
   ↓
[Knowledge Retrieval] 整形結果のタイトル+概要で既存を類似検索（重複チェック）
   ↓
[LLM-2: 判定] NEW / UPDATE / DUPLICATE / PARTIAL_OVERLAP
   出力(JSON): { judgment, target_page_id, reason, diff_summary }
   ↓
[Answer + 確認] ユーザーに判定と整形結果を提示
   「この内容で登録しますか？ [1]新規 [2]既存更新 [3]キャンセル」
   ↓ （Conversation Variable に整形済みドラフトを保持）
[IF: ユーザー応答]
   ├─ 新規     → [HTTP Request: POST docstore /pages]   （status: draft）
   ├─ 既存更新 → [HTTP Request: PUT  docstore /pages/{id}]（status: draft）
   └─ キャンセル → 終了
   ↓
[Answer: 完了通知] 「GROWI で確認・公開してください: {viewer_url}」
   ↓
─────────── ここから先は Dify の外（HITL）───────────
[ユーザーが GROWI でドラフトを確認・修正・公開]
   ↓
[GROWI 更新 → Sync Service が Dify Knowledge に反映]（Phase 1b）
```

---

## HITL の置き場所

| 案 | 内容 | 採否 |
|----|------|------|
| Dify チャット内で承認 | Bot が確認 → ユーザーが yes | 補助的に使う（登録前の意思確認） |
| **Wiki 上で編集・公開** | ドラフトを GROWI に作り、人が GROWI で仕上げて公開 | **主たる HITL。これを採用** |

理由:
- Markdown プレビュー・Mermaid 描画・画像確認は GROWI の方が得意
- 「整形ミスを手で直す」が GROWI の編集 UI で自由にできる
- 公開操作 = 承認、という自然な運用
- バージョン履歴が GROWI に残る

→ 登録 Bot は **ドラフトを置くところまで**。公開は人間が Wiki で行う。

---

## 重複判定ロジック（LLM-2）

登録 Bot の肝。多層防御の中核（[architecture.md](architecture.md) 参照）。

### 入力
- LLM-1 が整形した新ドラフト（タイトル + 概要 + 本文）
- Knowledge Retrieval が返した類似候補 N 件（page_id, title, viewer_url, 抜粋, score）

### 出力（JSON）
```json
{
  "judgment": "NEW | UPDATE | DUPLICATE | PARTIAL_OVERLAP",
  "target_page_id": "既存ページID（UPDATE/DUPLICATE/PARTIAL の場合）",
  "target_viewer_url": "既存ページURL",
  "confidence": 0.0,
  "reason": "判定の根拠",
  "diff_summary": "既存との差分の要約（UPDATE の場合）"
}
```

### 判定基準と処理

| judgment | 意味 | 処理 |
|----------|------|------|
| `NEW` | 既存に該当なし | 新規ドラフト作成（POST） |
| `UPDATE` | 既存の改訂版 | 既存を更新（PUT、status: draft）。差分をユーザーに提示 |
| `DUPLICATE` | ほぼ完全な重複 | 登録せず既存ページへ誘導 |
| `PARTIAL_OVERLAP` | 一部重複・一部新規 | 「既存の○章を更新 + 新規章を追加」を提案。ユーザー確認 |

**最終決定は必ずユーザー**。LLM-2 は提案、人が選ぶ（性善説運用なら本人が判断）。

---

## ドラフトの扱い

- 登録 Bot が作るページは必ず `status: draft`。
- Sync Service（Phase 1b）は `status: published` のみ Dify に同期する想定
  → ドラフトは検索対象に出ない（公開して初めて回答に使われる）。
  ※ この status フィルタは sync 側の拡張として 1b 検証後に追加する。
- 公開は人間が GROWI で `status: published` に変更して行う。

---

## Dify 内コンポーネントと外部依存

| ノード | 種別 | 外部依存 |
|--------|------|----------|
| Document Extractor | Dify 標準 | なし |
| LLM-1 整形 | LLM (Claude) | なし |
| Knowledge Retrieval | Dify 標準 | Dify Knowledge |
| LLM-2 判定 | LLM (Claude) | なし |
| ドラフト作成 | HTTP Request | **docstore-growi の POST/PUT /pages** |

→ 登録 Bot は Wiki 実装を知らない。**docstore-growi の契約（create/update）だけ**を叩く。
   Wiki を差し替えても登録 Bot は不変（設計原則どおり）。

---

## 未確定・1b 検証後に詰める点

1. **画像・図形を含むファイル**: Phase 2（Vision LLM 前処理）。1c はまずテキスト主体。
2. **Document Extractor の Word/Excel 抽出品質**: 実ファイルで要確認。
3. **status フィルタ同期**: sync が draft を除外する拡張。
4. **GROWI のドラフト表現**: status frontmatter で足りるか、パス分離が要るか。
5. **HTTP Request ノードの認証**: docstore-growi を内部ネットワークでどう呼ぶか。

---

## 成果物（予定）

- `dify/workflows/phase1c-registration-bot.yml`（Chatflow DSL）
- `dify/workflows/prompts/llm1-format.md`（整形プロンプト）
- `dify/workflows/prompts/llm2-dedup.md`（重複判定プロンプト）
- conventions/（テンプレート・ライティング規約）← 作成済み
