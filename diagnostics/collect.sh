#!/usr/bin/env bash
#
# 診断バンドル収集スクリプト（会社端末で実行する想定）
#
# 目的:
#   会社端末でしか繋がらない GROWI / Dify の状態を 1 つの zip にまとめ、
#   開発用 PC に持ち帰って解析・修正できるようにする。
#   （持ち帰り申請の回数を減らすための「まとめ取り」）
#
# 使い方:
#   bash diagnostics/collect.sh
#   ADAPTER_URL=http://localhost:8001 SYNC_URL=http://localhost:8002 \
#     bash diagnostics/collect.sh
#
# 前提:
#   - /debug 系は既定で無効。診断時はサービス側で DEBUG_ENDPOINTS_ENABLED=true にする。
#   - サービスに API キー認証を設定している場合は ADAPTER_API_KEY / SYNC_API_KEY を
#     環境変数で渡す（X-API-Key ヘッダとして送る。バンドルには記録しない）。
#
# 安全性:
#   - シークレット（トークン/APIキー）は収集しない。
#     env は「変数名と設定有無」だけを記録し、値は出さない。
#   - GROWI/Dify のレスポンス本文（マニュアル生値）は含まれる。
#     会社データを持ち出す前提の運用であること。
#
set -uo pipefail

ADAPTER_URL="${ADAPTER_URL:-http://localhost:8001}"
SYNC_URL="${SYNC_URL:-http://localhost:8002}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"
OUT_DIR="${ROOT_DIR}/diagnostics/out/bundle-${TS}"
mkdir -p "${OUT_DIR}"

echo "診断バンドルを収集します -> ${OUT_DIR}"

# curl ラッパー（失敗してもスクリプトは続行）
# URL が ADAPTER_URL / SYNC_URL のどちら宛かで対応する X-API-Key を付ける（未設定なら付けない）
fetch() {
  local label="$1" method="$2" url="$3" data="${4:-}"
  local outfile="${OUT_DIR}/${label}.json"
  local -a auth_args=()
  case "${url}" in
    "${ADAPTER_URL}"*) [ -n "${ADAPTER_API_KEY:-}" ] && auth_args=(-H "X-API-Key: ${ADAPTER_API_KEY}") ;;
    "${SYNC_URL}"*)    [ -n "${SYNC_API_KEY:-}" ]    && auth_args=(-H "X-API-Key: ${SYNC_API_KEY}") ;;
  esac
  echo "  [${method}] ${url}  -> ${label}.json"
  # ${auth_args[@]+...} は bash 3.2 + set -u で空配列を安全に展開するイディオム
  if [ "${method}" = "POST" ]; then
    curl -sS -m 60 -X POST "${url}" \
      -H 'Content-Type: application/json' ${auth_args[@]+"${auth_args[@]}"} -d "${data}" \
      -o "${outfile}" -w '{"_http_status":%{http_code}}\n' \
      > "${OUT_DIR}/${label}.status" 2>"${OUT_DIR}/${label}.err" || true
  else
    curl -sS -m 60 "${url}" ${auth_args[@]+"${auth_args[@]}"} \
      -o "${outfile}" -w '{"_http_status":%{http_code}}\n' \
      > "${OUT_DIR}/${label}.status" 2>"${OUT_DIR}/${label}.err" || true
  fi
}

echo "[1/5] サービス状態"
fetch "adapter-info"   GET "${ADAPTER_URL}/info"
fetch "adapter-health" GET "${ADAPTER_URL}/health"
fetch "sync-info"      GET "${SYNC_URL}/info"
fetch "sync-health"    GET "${SYNC_URL}/health"

echo "[2/5] GROWI 生レスポンス（mappers 調整用）"
fetch "growi-raw-pages"  GET "${ADAPTER_URL}/debug/raw/pages?limit=10"
fetch "growi-raw-recent" GET "${ADAPTER_URL}/debug/raw/recent?limit=10"
# 先頭ページの id を取り出して 1 件詳細も取る（jq が無くても動くよう grep で代替）
FIRST_ID="$(grep -o '"_id"[ ]*:[ ]*"[^"]*"' "${OUT_DIR}/growi-raw-pages.json" 2>/dev/null \
  | head -n1 | sed 's/.*"\([^"]*\)"$/\1/')"
if [ -n "${FIRST_ID:-}" ]; then
  fetch "growi-raw-page-first" GET "${ADAPTER_URL}/debug/raw/page/${FIRST_ID}"
fi

echo "[3/5] Dify / DocStore 生レスポンス"
fetch "dify-raw-documents"  GET "${SYNC_URL}/debug/raw/dify-documents"
fetch "docstore-raw-pages"  GET "${SYNC_URL}/debug/raw/docstore-pages"

echo "[4/5] dry-run 同期レポート"
fetch "sync-dryrun-full" POST "${SYNC_URL}/sync" '{"mode":"full","dry_run":true}'

echo "[5/5] ログ・環境情報"
# サービスのログファイルを収集
for svc in docstore-growi sync; do
  if [ -d "${ROOT_DIR}/services/${svc}/logs" ]; then
    mkdir -p "${OUT_DIR}/logs/${svc}"
    cp -f "${ROOT_DIR}/services/${svc}/logs/"*.log* "${OUT_DIR}/logs/${svc}/" 2>/dev/null || true
  fi
done

# RAG 品質評価の結果（evaluation/run_eval.py の出力）があれば含める
if [ -d "${ROOT_DIR}/evaluation/out" ]; then
  mkdir -p "${OUT_DIR}/evaluation"
  cp -Rf "${ROOT_DIR}/evaluation/out/." "${OUT_DIR}/evaluation/" 2>/dev/null || true
fi

# 環境メタ（※ env の値は出さない。名前と設定有無のみ）
{
  echo "collected_at: ${TS}"
  echo "adapter_url: ${ADAPTER_URL}"
  echo "sync_url: ${SYNC_URL}"
  echo "uname: $(uname -a 2>/dev/null || echo n/a)"
  echo "python: $(python3 --version 2>&1 || echo n/a)"
  echo "git_rev: $(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo n/a)"
  echo "git_status_short:"
  git -C "${ROOT_DIR}" status --short 2>/dev/null || true
} > "${OUT_DIR}/environment.txt"

# シークレット系の env は「設定有無」だけ記録（値は絶対に出さない）
{
  echo "# 環境変数の設定有無のみ（値は記録しない）"
  for var in GROWI_BASE_URL GROWI_API_TOKEN DOCSTORE_URL \
             DIFY_API_BASE_URL DIFY_API_KEY DIFY_DATASET_ID \
             ADAPTER_API_KEY SYNC_API_KEY DOCSTORE_API_KEY; do
    if [ -n "${!var:-}" ]; then
      echo "${var}=SET"
    else
      echo "${var}=unset"
    fi
  done
} > "${OUT_DIR}/env-presence.txt"

# zip にまとめる
ZIP_PATH="${ROOT_DIR}/diagnostics/out/bundle-${TS}.zip"
if command -v zip >/dev/null 2>&1; then
  (cd "${ROOT_DIR}/diagnostics/out" && zip -rq "bundle-${TS}.zip" "bundle-${TS}")
  echo ""
  echo "完成: ${ZIP_PATH}"
  echo "この zip を開発用 PC に持ち帰ってください。"
else
  echo ""
  echo "zip コマンドが無いため、フォルダのまま残します: ${OUT_DIR}"
  echo "手動で圧縮して持ち帰ってください。"
fi
