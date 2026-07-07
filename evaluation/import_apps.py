"""Bot DSL を環境値でパッチして Dify に一括インポートする（会社端末で実行する想定）。

configuration.md の「インポート後に差し替える箇所」を UI 手作業でなくスクリプトで行い、
現地での試行錯誤を減らす。会社端末の制約（プロキシのホワイトリスト）を踏まえ、
**標準ライブラリのみ**で動く（YAML パーサ不要のテキストパッチ。パッチが 1 件も
当たらない場合はエラーにして黙って壊れるのを防ぐ）。

    DIFY_BASE_URL=http://<dify> DIFY_EMAIL=... DIFY_PASSWORD=... \
    DATASET_ID=<ナレッジのID> \
    [MODEL_PROVIDER=langgenius/openai/openai MODEL_NAME=gpt-4o-mini] \
    [RERANKER=weighted]  [DOCSTORE_URL=http://docstore-growi:8001] \
    [APPS=qa,register,unified] \
    python evaluation/import_apps.py

- DATASET_ID: 事前に Dify UI で作成したナレッジの ID（URL の /datasets/<ID>/ 部分）
- MODEL_*: 省略時は DSL の既定（gpt-4o-mini）。社内の LLM に合わせて指定する
- RERANKER=weighted（既定）: Reranker 未設定環境向けに weighted_score へ書き換える。
  Reranker がある環境では RERANKER=keep とし、インポート後に UI で設定する
- APPS: qa / register / bulk / dedup / unified のカンマ区切り（既定 qa,register,unified）
"""

import http.cookiejar
import json
import os
import re
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / "dify" / "workflows"

BASE_URL = os.environ.get("DIFY_BASE_URL", "http://localhost").rstrip("/")
EMAIL = os.environ.get("DIFY_EMAIL", "")
PASSWORD = os.environ.get("DIFY_PASSWORD", "")
DATASET_ID = os.environ.get("DATASET_ID", "")
MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "")
MODEL_NAME = os.environ.get("MODEL_NAME", "")
RERANKER = os.environ.get("RERANKER", "weighted")
DOCSTORE_URL = os.environ.get("DOCSTORE_URL", "")
APPS = [a.strip() for a in os.environ.get("APPS", "qa,register,unified").split(",") if a.strip()]

FILES = {
    "qa": "phase1a-qa-bot.yml",
    "register": "phase1c-registration-bot.yml",
    "bulk": "bulk-import-bot.yml",
    "dedup": "dedup-bot.yml",
    "unified": "unified-chat-bot.yml",
}

# Reranker プレースホルダのブロック → weighted_score（qa / unified の 2 形式に対応）
_RERANK_BLOCK = re.compile(
    r"reranking_enable: true\n"
    r"(?P<i>\s+)reranking_mode: reranking_model\n"
    r"\s+reranking_model:\n"
    r"\s+provider: .*\n"
    r"\s+model: .*\n"
)


def _weighted(match: re.Match) -> str:
    i = match.group("i")
    return (
        f"reranking_enable: false\n"
        f"{i}reranking_mode: weighted_score\n"
        f"{i}weights:\n"
        f"{i}  vector_setting:\n"
        f"{i}    vector_weight: 1.0\n"
        f"{i}    embedding_provider_name: ''\n"
        f"{i}    embedding_model_name: ''\n"
        f"{i}  keyword_setting:\n"
        f"{i}    keyword_weight: 0.0\n"
    )


def patch(name: str, text: str) -> str:
    """DSL テキストを環境値でパッチする。当たらなかったパッチはエラーにする。"""
    # 1) dataset_ids: プレースホルダも、エクスポート時の不透明 ID も置き換える
    if DATASET_ID:
        text = text.replace("REPLACE_WITH_YOUR_DATASET_ID", DATASET_ID)
        text, _n = re.subn(
            r"(dataset_ids:\n\s+- )[^\n]+", rf"\g<1>{DATASET_ID}", text
        )
    if "REPLACE_WITH_YOUR_DATASET_ID" in text:
        raise SystemExit(f"{name}: DATASET_ID を指定してください（プレースホルダが残っています）")

    # 2) Reranker 未設定環境向けの書き換え
    if RERANKER == "weighted":
        text = _RERANK_BLOCK.sub(_weighted, text)
    if "REPLACE_WITH_RERANKER" in text:
        raise SystemExit(
            f"{name}: Reranker プレースホルダが残っています"
            "（RERANKER=weighted にするか、keep の場合はインポート後に UI で設定）"
        )

    # 3) LLM モデルの差し替え（省略時は DSL の既定のまま）
    if MODEL_PROVIDER:
        text, n = re.subn(r"provider: langgenius/openai/openai\b", f"provider: {MODEL_PROVIDER}", text)
        text = text.replace("provider: anthropic", f"provider: {MODEL_PROVIDER}")
    if MODEL_NAME:
        text = text.replace("name: gpt-4o-mini", f"name: {MODEL_NAME}")
        text = re.sub(r"name: claude-[a-z0-9.-]+", f"name: {MODEL_NAME}", text)

    # 4) DocStore Adapter の到達 URL（DSL の environment_variables 既定値）
    if DOCSTORE_URL:
        text = text.replace("value: http://docstore-growi:8001", f"value: {DOCSTORE_URL}")
    return text


def main() -> None:
    if not (EMAIL and PASSWORD):
        raise SystemExit("環境変数 DIFY_EMAIL / DIFY_PASSWORD を設定してください")
    unknown = [a for a in APPS if a not in FILES]
    if unknown:
        raise SystemExit(f"APPS の指定が不正です: {unknown}（{'/'.join(FILES)} から選ぶ）")

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def post(path: str, payload: dict) -> dict:
        csrf = next((c.value for c in jar if c.name == "csrf_token"), "")
        req = urllib.request.Request(
            f"{BASE_URL}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-CSRF-Token": csrf or ""},
            method="POST",
        )
        with opener.open(req, timeout=120) as resp:
            return json.loads(resp.read())

    login = post(
        "/console/api/login",
        {"email": EMAIL, "password": PASSWORD, "language": "ja-JP", "remember_me": True},
    )
    if login.get("result") != "success":
        raise SystemExit(f"Dify ログイン失敗: {login}")

    out_lines = []
    for app in APPS:
        path = WORKFLOWS / FILES[app]
        text = patch(FILES[app], path.read_text(encoding="utf-8"))
        result = post(
            "/console/api/apps/imports", {"mode": "yaml-content", "yaml_content": text}
        )
        status, app_id = result.get("status"), result.get("app_id")
        line = f"{app:10s} -> {status}  app_id={app_id}"
        print(line, result.get("error") or "")
        out_lines.append(line)
        if status not in ("completed", "completed-with-warnings"):
            raise SystemExit(f"{app} のインポートに失敗しました: {result}")

    out = REPO / "evaluation" / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "app-ids.txt").write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"\napp_id 一覧を {out / 'app-ids.txt'} に保存しました")
    print("質問Bot(qa)の app_id を EVAL_APP_ID に指定して run_eval.py を実行してください")


if __name__ == "__main__":
    main()
