"""RAG 品質評価ランナー（Phase 1a ゲート用・会社端末で実行する想定）。

questions.tsv の質問を質問 Bot（または統一チャット）に順に投げ、
回答・引用・応答時間を収集して、人間が採点するためのレポートを出力する。

会社端末の制約（プロキシのホワイトリスト）を踏まえ、**標準ライブラリのみ**で動く。
pip / uv でのパッケージ取得は不要。Python 3.11+ で実行:

    DIFY_BASE_URL=http://<dify> DIFY_EMAIL=... DIFY_PASSWORD=... \
    EVAL_APP_ID=<質問BotのアプリID> \
    python evaluation/run_eval.py [questions.tsv]

出力（evaluation/out/eval-<timestamp>/）:
- results.jsonl : 全質問の生データ（回答全文・引用・応答秒・SSEステータス）
- report.md     : 採点用レポート（ルーブリック列は空欄。人間が ◎○△× を記入する）

判定基準は docs/phase-plan.md の Phase 1a 評価ルーブリックに従う。
シークレット（パスワード等）は出力ファイルに記録しない。
"""

import csv
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

BASE_URL = os.environ.get("DIFY_BASE_URL", "http://localhost").rstrip("/")
EMAIL = os.environ.get("DIFY_EMAIL", "")
PASSWORD = os.environ.get("DIFY_PASSWORD", "")
APP_ID = os.environ.get("EVAL_APP_ID", "")
# 1 質問あたりのタイムアウト秒（LLM が遅い環境では引き上げる）
TIMEOUT = int(os.environ.get("EVAL_TIMEOUT", "180"))


class DifyConsole:
    """Dify コンソール API の最小クライアント（cookie + CSRF。標準ライブラリのみ）。"""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def _csrf(self) -> str:
        for c in self.jar:
            if c.name == "csrf_token":
                return c.value or ""
        return ""

    def post(self, path: str, payload: dict, timeout: int = 60):
        """JSON POST。レスポンスオブジェクトを返す（SSE はストリームで読む）。"""
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "X-CSRF-Token": self._csrf(),
            },
            method="POST",
        )
        return self.opener.open(req, timeout=timeout)

    def login(self, email: str, password: str) -> None:
        resp = self.post(
            "/console/api/login",
            {"email": email, "password": password, "language": "ja-JP", "remember_me": True},
        )
        body = json.loads(resp.read())
        if body.get("result") != "success":
            raise SystemExit(f"Dify ログイン失敗: {body}")

    def run_chat(self, app_id: str, query: str, timeout: int) -> dict:
        """draft 実行（SSE）を最後まで読み、回答・引用・状態を返す。"""
        started = time.monotonic()
        answer = ""
        status = None
        error = None
        sources: list[dict] = []
        try:
            resp = self.post(
                f"/console/api/apps/{app_id}/advanced-chat/workflows/draft/run",
                {"query": query, "inputs": {}, "files": []},
                timeout=timeout,
            )
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                try:
                    d = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                ev = d.get("event")
                if ev == "message":
                    answer += d.get("answer", "")
                elif ev == "message_end":
                    for r in (d.get("metadata") or {}).get("retriever_resources") or []:
                        sources.append(
                            {
                                "document_name": r.get("document_name", ""),
                                "score": r.get("score"),
                            }
                        )
                elif ev == "workflow_finished":
                    status = (d.get("data") or {}).get("status")
                elif ev == "node_finished":
                    data = d.get("data") or {}
                    if data.get("status") not in (None, "succeeded"):
                        error = f"{data.get('title')}: {str(data.get('error'))[:200]}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = f"リクエスト失敗: {exc}"
        return {
            "answer": answer,
            "status": status,
            "error": error,
            "sources": sources,
            "elapsed_sec": round(time.monotonic() - started, 1),
        }


def load_questions(path: Path) -> list[dict]:
    """TSV（ヘッダ行つき）を読む。列: id, question, expected_source, note。"""
    rows: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if not (row.get("question") or "").strip():
                continue
            rows.append(
                {
                    "id": (row.get("id") or str(len(rows) + 1)).strip(),
                    "question": row["question"].strip(),
                    "expected_source": (row.get("expected_source") or "").strip(),
                    "note": (row.get("note") or "").strip(),
                }
            )
    return rows


def write_report(out_dir: Path, results: list[dict]) -> None:
    ok = [r for r in results if not r["result"]["error"]]
    lat = [r["result"]["elapsed_sec"] for r in ok]
    lines = [
        "# RAG 品質評価レポート（Phase 1a ゲート）",
        "",
        f"- 実行日時: {datetime.now().isoformat(timespec='seconds')}",
        f"- 質問数: {len(results)} / エラー: {len(results) - len(ok)}",
        f"- 応答時間: 平均 {sum(lat)/len(lat):.1f} 秒 / 最大 {max(lat):.1f} 秒" if lat else "- 応答時間: n/a",
        "",
        "## 採点のしかた（docs/phase-plan.md のルーブリック）",
        "",
        "各行の空欄に ◎ / ○ / △ / × を記入する（「該当なし判定」列は ◎ / × のみ）。",
        "**意思決定: ◎○ が 70% 以上 → 次フェーズへ / 50-70% → コンテンツ整備を先に /",
        "50% 未満 → アーキテクチャ見直し**",
        "",
        "| # | 質問 | 応答秒 | 正確性 | 完全性 | 出典妥当性 | 該当なし判定 | メモ |",
        "|---|------|--------|--------|--------|-----------|--------------|------|",
    ]
    for r in results:
        res = r["result"]
        q = r["question"].replace("|", "／")
        note = ("ERROR: " + res["error"]) if res["error"] else r.get("note", "")
        lines.append(
            f"| {r['id']} | {q} | {res['elapsed_sec']} |  |  |  |  | {note.replace('|', '／')[:60]} |"
        )
    lines += ["", "## 各回答（採点時に参照）", ""]
    for r in results:
        res = r["result"]
        lines += [
            f"### {r['id']}. {r['question']}",
            "",
            f"- 期待する出典: {r['expected_source'] or '（指定なし）'}",
            f"- 実際の引用: {', '.join(s['document_name'] for s in res['sources']) or '（なし）'}",
            f"- 応答: {res['elapsed_sec']} 秒 / status={res['status']}"
            + (f" / **{res['error']}**" if res["error"] else ""),
            "",
            "```",
            res["answer"] or "(回答なし)",
            "```",
            "",
        ]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not (EMAIL and PASSWORD and APP_ID):
        raise SystemExit(
            "環境変数 DIFY_EMAIL / DIFY_PASSWORD / EVAL_APP_ID を設定してください"
            "（DIFY_BASE_URL の既定は http://localhost）"
        )
    q_path = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "evaluation" / "questions.tsv"
    if not q_path.exists():
        raise SystemExit(
            f"質問ファイルが見つかりません: {q_path}\n"
            "evaluation/questions.example.tsv を questions.tsv にコピーして実質問を書いてください"
        )
    questions = load_questions(q_path)
    print(f"質問 {len(questions)} 件を {BASE_URL} のアプリ {APP_ID} に対して実行します")

    console = DifyConsole(BASE_URL)
    console.login(EMAIL, PASSWORD)

    out_dir = REPO / "evaluation" / "out" / f"eval-{datetime.now():%Y%m%d-%H%M%S}"
    out_dir.mkdir(parents=True)

    results: list[dict] = []
    with (out_dir / "results.jsonl").open("w", encoding="utf-8") as jl:
        for q in questions:
            print(f"  [{q['id']}] {q['question'][:40]}... ", end="", flush=True)
            res = console.run_chat(APP_ID, q["question"], timeout=TIMEOUT)
            print(f"{res['elapsed_sec']}s" + (" ERROR" if res["error"] else ""))
            record = {**q, "result": res}
            results.append(record)
            jl.write(json.dumps(record, ensure_ascii=False) + "\n")

    write_report(out_dir, results)
    print(f"\n完了: {out_dir}/report.md に採点表を出力しました")
    print("採点後、diagnostics/collect.sh で out/ ごとバンドルして持ち帰ってください")


if __name__ == "__main__":
    main()
