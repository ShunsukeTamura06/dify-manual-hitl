"""統一チャット（完全 bot）の Chatflow DSL を既存 4 Bot の検証済み DSL から機械合成する。

手作業のコピペで参照（value_selector / iteration_id / {{#node.field#}}）を壊さないため、
ノード ID の名前空間化と参照の再配線をスクリプトで行う（docs/unified-chat-design.md）。

使い方:
    cd dify/unified-chat
    uv run --with pyyaml python tools/build_dsl.py
    → dify/workflows/unified-chat-bot.yml を生成

合成規則:
- 登録 Bot をベースに、その start / doc_extractor を共有ノードとして使う。
- QA Bot は q_、一括取り込み Bot は b_、重複排除 Bot は d_ 接頭辞で名前空間化。
- doc_extractor の後ろに ルーターLLM(意図分類) → ルーター(Code・決定的サニタイズ)
  → IF/ELSE を挿入し、qa / register / bulk / dedup / pending の 5 分岐にする。
- pending 分岐（承認待ち一覧・読み取り専用）は本スクリプトが直接組み立てる
  （元 DSL に対応する Bot が無いため。アダプタの GET /pages/pending-approval を叩くだけ）。
- 各フローのノード・プロンプト・接続は変更しない（実機検証済みの資産を保全）。
"""

import copy
import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / "dify" / "workflows"
ROUTER_CODE = (REPO / "dify" / "unified-chat" / "router" / "routing.py").read_text()
OUT = WORKFLOWS / "unified-chat-bot.yml"

# ID 参照を持つキー（単一文字列）
_ID_KEYS = {"source", "target", "parentId", "iteration_id", "start_node_id"}
# ID 参照を持つキー（[node_id, field, ...] 形式のリスト）
_SELECTOR_KEYS = {
    "value_selector",
    "variable_selector",
    "query_variable_selector",
    "output_selector",
    "iterator_selector",
}


def _rename(obj: Any, mapping: dict[str, str]) -> Any:
    """ノード/エッジ構造内の ID 参照とテンプレート参照を一括で付け替える。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _ID_KEYS and isinstance(v, str) and v in mapping:
                out[k] = mapping[v]
            elif k == "id" and isinstance(v, str) and v in mapping:
                out[k] = mapping[v]
            elif (
                k in _SELECTOR_KEYS
                and isinstance(v, list)
                and v
                and isinstance(v[0], str)
                and v[0] in mapping
            ):
                out[k] = [mapping[v[0]], *_rename(v[1:], mapping)]
            else:
                out[k] = _rename(v, mapping)
        return out
    if isinstance(obj, list):
        return [_rename(x, mapping) for x in obj]
    if isinstance(obj, str):
        for old, new in mapping.items():
            obj = obj.replace("{{#" + old + ".", "{{#" + new + ".")
        return obj
    return obj


def _shift(nodes: list[dict], dy: int) -> None:
    """UI 上の重なりを避けるため座標をずらす（動作には無関係）。"""
    for n in nodes:
        for key in ("position", "positionAbsolute"):
            if isinstance(n.get(key), dict) and "y" in n[key]:
                n[key]["y"] += dy


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _take(dsl: dict, drop_ids: set[str], prefix: str) -> tuple[list[dict], list[dict]]:
    """DSL からノード/エッジを取り出し、drop を除き prefix で名前空間化する。"""
    graph = copy.deepcopy(dsl["workflow"]["graph"])
    nodes = [n for n in graph["nodes"] if n["id"] not in drop_ids]
    edges = [
        e
        for e in graph["edges"]
        if e["source"] not in drop_ids and e["target"] not in drop_ids
    ]
    mapping = {n["id"]: f"{prefix}{n['id']}" for n in nodes} if prefix else {}
    return _rename(nodes, mapping), _rename(edges, mapping)


def _edge(source: str, target: str, handle: str = "source") -> dict:
    return {
        "id": f"{source}-{handle}-{target}",
        "source": source,
        "sourceHandle": handle,
        "target": target,
        "targetHandle": "target",
        "type": "custom",
    }


def build() -> dict:
    reg = _load("phase1c-registration-bot.yml")
    qa = _load("phase1a-qa-bot.yml")
    bulk = _load("bulk-import-bot.yml")
    dedup = _load("dedup-bot.yml")

    # ── 各 Bot からノード/エッジを取り出す ──
    # 登録 Bot: start / doc_extractor を共有ノードとして残す。doc_extractor→llm1 は
    # ルーター経由に置き換えるため落とす。
    reg_nodes, reg_edges = _take(reg, drop_ids=set(), prefix="")
    reg_edges = [
        e
        for e in reg_edges
        if not (e["source"] == "doc_extractor" and e["target"] == "llm1")
    ]

    # QA: start を捨てて q_ 名前空間化
    qa_nodes, qa_edges = _take(qa, drop_ids={"start"}, prefix="q_")
    _shift(qa_nodes, -400)

    # 一括取り込み: start と（共有と重複する）doc_extractor を捨てて b_ 名前空間化。
    # 抽出テキストへの参照は共有 doc_extractor と同名なのでそのまま解決される。
    bulk_nodes, bulk_edges = _take(bulk, drop_ids={"start", "doc_extractor"}, prefix="b_")
    _shift(bulk_nodes, 600)

    # 重複排除: start を捨てて d_ 名前空間化。入口は d_scope（sys.query から対象パスを決める）。
    dedup_nodes, dedup_edges = _take(dedup, drop_ids={"start"}, prefix="d_")
    _shift(dedup_nodes, 1100)

    # 登録フローの LLM モデル（ルーターLLM と qa の既定に流用。環境で差し替え可）
    reg_llm_model = next(n for n in reg_nodes if n["id"] == "llm1")["data"]["model"]

    # ── ルーターLLM（意図分類・自律判断）──
    router_llm_node = {
        "data": {
            "type": "llm",
            "title": "意図分類(ルーターLLM)",
            "desc": "意図を qa/register/bulk/dedup/pending に分類。最終決定はルーターCodeが事実で矯正",
            "model": {
                **copy.deepcopy(reg_llm_model),
                # Claude Sonnet 5 系は 1.0 以外を受け付けないモデルがあるため既定を 1.0 に
                "completion_params": {"temperature": 1.0, "max_tokens": 20},
            },
            "prompt_template": [
                {
                    "role": "system",
                    "text": (
                        "ユーザーのメッセージから、望む操作を1語で分類せよ。\n"
                        "- qa: マニュアルの内容について質問している\n"
                        "- register: 資料（ファイル）を登録・更新したい\n"
                        "- bulk: 大きな資料を分割して一括取り込みしたい\n"
                        "- dedup: 既存ページの重複を整理・確認したい\n"
                        "- pending: 承認待ち（下書き）のページ一覧を知りたい\n"
                        "迷ったら qa。回答は qa / register / bulk / dedup / pending のいずれか1語のみ。"
                    ),
                },
                {"role": "user", "text": "{{#sys.query#}}"},
            ],
            "context": {"enabled": False, "variable_selector": []},
            "vision": {"enabled": False},
        },
        "id": "router_llm",
        "position": {"x": 500, "y": 282},
        "type": "custom",
    }

    # ── ルーター（Code・決定的サニタイズ）と IF/ELSE ──
    router_node = {
        "data": {
            "type": "code",
            "title": "ルーター(決定的)",
            "desc": "添付有無・文字数・キーワード + LLM意図 で qa/register/bulk/dedup を決定",
            "code_language": "python3",
            "code": ROUTER_CODE,
            "outputs": {"route": {"type": "string"}},
            "variables": [
                {"variable": "query", "value_selector": ["sys", "query"]},
                {"variable": "extracted_text", "value_selector": ["doc_extractor", "text"]},
                {"variable": "llm_intent", "value_selector": ["router_llm", "text"]},
            ],
        },
        "id": "router",
        "position": {"x": 700, "y": 282},
        "type": "custom",
    }
    ifelse_node = {
        "data": {
            "type": "if-else",
            "title": "ルート分岐",
            "desc": "qa / register / それ以外(bulk)",
            "cases": [
                {
                    "case_id": "case_qa",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "id": "cond_qa",
                            "comparison_operator": "is",
                            "value": "qa",
                            "varType": "string",
                            "variable_selector": ["router", "route"],
                        }
                    ],
                },
                {
                    "case_id": "case_register",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "id": "cond_register",
                            "comparison_operator": "is",
                            "value": "register",
                            "varType": "string",
                            "variable_selector": ["router", "route"],
                        }
                    ],
                },
                # bulk / dedup も明示 case にする。ELSE（既定）を書込系フローに向けない:
                # ルーター出力が想定外（空・将来の値追加）でも書込が誤発火しない。
                {
                    "case_id": "case_bulk",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "id": "cond_bulk",
                            "comparison_operator": "is",
                            "value": "bulk",
                            "varType": "string",
                            "variable_selector": ["router", "route"],
                        }
                    ],
                },
                {
                    "case_id": "case_dedup",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "id": "cond_dedup",
                            "comparison_operator": "is",
                            "value": "dedup",
                            "varType": "string",
                            "variable_selector": ["router", "route"],
                        }
                    ],
                },
                {
                    "case_id": "case_pending",
                    "logical_operator": "and",
                    "conditions": [
                        {
                            "id": "cond_pending",
                            "comparison_operator": "is",
                            "value": "pending",
                            "varType": "string",
                            "variable_selector": ["router", "route"],
                        }
                    ],
                },
            ],
        },
        "id": "route_ifelse",
        "position": {"x": 960, "y": 282},
        "type": "custom",
    }
    fallback_node = {
        "data": {
            "type": "answer",
            "title": "判定不能時の案内",
            "desc": "ルーター出力が想定外のときの安全側フォールバック（書き込まない）",
            "answer": (
                "ご依頼を判定できませんでした（route={{#router.route#}}）。\n"
                "・質問の場合: そのままメッセージでお送りください\n"
                "・登録の場合: ファイルを添付してください\n"
                "・重複整理の場合: 「/manuals/… の重複を整理して」のようにお伝えください\n"
                "・承認待ち確認の場合: 「承認待ちのページは？」のようにお伝えください\n"
            ),
        },
        "id": "route_fallback_answer",
        "position": {"x": 1160, "y": 120},
        "type": "custom",
    }

    # ── pending 分岐（承認待ち一覧。読み取り専用・HITL 運用の可視化）──
    # アダプタの GET /pages/pending-approval を叩いて整形するだけ。書込は一切しない。
    p_http = {
        "data": {
            "type": "http-request",
            "title": "承認待ち一覧取得",
            "desc": "Wiki 全体の status:draft ページを取得（アダプタ側で本文取得して判定済み）",
            "method": "get",
            "url": "{{#env.DOCSTORE_URL#}}/pages/pending-approval?limit=500",
            "authorization": {"config": None, "type": "no-auth"},
            "body": {"data": "", "type": "none"},
            "headers": "X-API-Key:{{#env.DOCSTORE_API_KEY#}}",
            "params": "",
            "timeout": {"max_connect_timeout": 10, "max_read_timeout": 60, "max_write_timeout": 60},
        },
        "id": "p_http_pending",
        "position": {"x": 1900, "y": 560},
        "type": "custom",
    }
    p_format_code = '''
import json


def main(body: str) -> dict:
    try:
        d = json.loads(body) if isinstance(body, str) else (body or {})
    except Exception:
        d = {}
    pages = d.get("pages", []) if isinstance(d, dict) else []
    if not pages:
        return {"text": "承認待ち（下書き）のページはありません。"}
    lines = [f"承認待ち（status: draft）のページが {len(pages)} 件あります。", ""]
    for p in pages:
        title = p.get("title", "")
        path = p.get("path", "")
        url = p.get("viewer_url", "")
        updated = p.get("updated_at", "")
        lines.append(f"- {title}（{path}）")
        lines.append(f"  更新: {updated} / {url}")
    lines.append("")
    lines.append("GROWI で内容を確認し、frontmatter の status を published にすると検索に反映されます。")
    return {"text": "\\n".join(lines)}
'''
    p_format = {
        "data": {
            "type": "code",
            "title": "承認待ち一覧を整形",
            "desc": "取得結果を読みやすいテキストに整形する（書込は行わない）",
            "code_language": "python3",
            "code": p_format_code,
            "outputs": {"text": {"type": "string"}},
            "variables": [{"variable": "body", "value_selector": ["p_http_pending", "body"]}],
        },
        "id": "p_format",
        "position": {"x": 2160, "y": 560},
        "type": "custom",
    }
    p_answer = {
        "data": {
            "type": "answer",
            "title": "承認待ち一覧を返す",
            "answer": "{{#p_format.text#}}",
            "variables": [],
        },
        "id": "p_answer",
        "position": {"x": 2420, "y": 560},
        "type": "custom",
    }

    # qa 分岐の LLM は登録フローと同じモデルに揃える（dependencies と整合させるため。
    # インポート後に任意の LLM へ差し替え可能な点は変わらない）
    q_llm = next(n for n in qa_nodes if n["id"] == "q_llm")
    q_llm["data"]["model"] = {**q_llm["data"]["model"], **copy.deepcopy(reg_llm_model)}

    nodes = (
        reg_nodes
        + qa_nodes
        + bulk_nodes
        + dedup_nodes
        + [
            router_llm_node,
            router_node,
            ifelse_node,
            fallback_node,
            p_http,
            p_format,
            p_answer,
        ]
    )
    edges = (
        reg_edges
        + qa_edges
        + bulk_edges
        + dedup_edges
        + [
            _edge("doc_extractor", "router_llm"),
            _edge("router_llm", "router"),
            _edge("router", "route_ifelse"),
            _edge("route_ifelse", "q_knowledge_retrieval", handle="case_qa"),
            _edge("route_ifelse", "llm1", handle="case_register"),
            _edge("route_ifelse", "b_split_windows", handle="case_bulk"),
            _edge("route_ifelse", "d_scope", handle="case_dedup"),
            _edge("route_ifelse", "p_http_pending", handle="case_pending"),
            _edge("route_ifelse", "route_fallback_answer", handle="false"),
            _edge("p_http_pending", "p_format"),
            _edge("p_format", "p_answer"),
        ]
    )
    # エッジ ID の重複を避ける（各 Bot 由来の e1 等が衝突しうる）
    for e in edges:
        e["id"] = f"{e['source']}-{e.get('sourceHandle','source')}-{e['target']}"

    # ── アプリ全体 ──
    features = copy.deepcopy(reg["workflow"]["features"])
    features["opening_statement"] = (
        "マニュアルのことは何でもここへどうぞ。用件は自動で振り分けます。\n"
        "・質問: そのまま聞いてください（出典付きで回答します）\n"
        "・登録/更新: ファイルを添付してください（大きい文書は自動で分割します）\n"
        "・重複の整理: 「/manuals/… の重複を整理して」とお伝えください\n"
        "・承認待ち確認: 「承認待ちのページは？」とお伝えください\n"
        "登録されたページは下書きになり、GROWI で公開すると検索に反映されます。\n"
    )
    features["retriever_resource"] = {"enabled": True}

    return {
        "app": {
            "description": (
                "マニュアルアシスタント（完全 bot）。質問・登録・一括取り込み・重複整理・"
                "承認待ち確認を 1 つの入口で受け、LLM 意図分類 + 決定的サニタイズで"
                "自律的に振り分ける。"
            ),
            "icon": "💬",
            "icon_background": "#D5F5F6",
            "mode": "advanced-chat",
            "name": "マニュアルアシスタント",
            "use_icon_as_answer_icon": False,
        },
        "dependencies": copy.deepcopy(reg.get("dependencies", [])),
        "kind": "app",
        "version": reg.get("version", "0.4.0"),
        "workflow": {
            "conversation_variables": [],
            "environment_variables": copy.deepcopy(
                reg["workflow"]["environment_variables"]
            ),
            "features": features,
            "graph": {"edges": edges, "nodes": nodes},
        },
    }


def validate(dsl: dict) -> list[str]:
    """参照切れを検出する（エッジ端点・セレクタ先頭・テンプレート参照）。"""
    nodes = dsl["workflow"]["graph"]["nodes"]
    edges = dsl["workflow"]["graph"]["edges"]
    ids = {n["id"] for n in nodes}
    known = ids | {"sys", "env", "conversation"}
    errors: list[str] = []

    for e in edges:
        for end in ("source", "target"):
            if e[end] not in ids:
                errors.append(f"edge {e['id']}: {end}={e[end]} が存在しない")

    def walk(obj: Any, where: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in _SELECTOR_KEYS and isinstance(v, list) and v:
                    if isinstance(v[0], str) and v[0] not in known:
                        errors.append(f"{where}: {k}={v} の参照先が存在しない")
                else:
                    walk(v, where)
        elif isinstance(obj, list):
            for x in obj:
                walk(x, where)
        elif isinstance(obj, str):
            for ref in re.findall(r"\{\{#([A-Za-z0-9_]+)\.", obj):
                if ref not in known:
                    errors.append(f"{where}: テンプレート参照 {{{{#{ref}.…}}}} が存在しない")

    for n in nodes:
        walk(n["data"], f"node {n['id']}")

    # エッジ ID の一意性
    edge_ids = [e["id"] for e in edges]
    if len(edge_ids) != len(set(edge_ids)):
        errors.append("エッジ ID が重複している")

    # iteration-start ノードは外側 type が custom-iteration-start でないと
    # Dify のキャンバス描画が壊れる（React error #130。バックエンド実行は
    # 影響を受けないため API 経由のテストでは検出できない、要注意ポイント）。
    for n in nodes:
        if n["data"].get("type") == "iteration-start" and n.get("type") != "custom-iteration-start":
            errors.append(
                f"node {n['id']}: iteration-start ノードの外側 type が "
                f"{n.get('type')!r}（custom-iteration-start であるべき）"
            )
    return errors


def main() -> None:
    dsl = build()
    errors = validate(dsl)
    if errors:
        for e in errors:
            print("NG:", e)
        raise SystemExit(1)
    header = (
        "# マニュアルアシスタント（完全 bot）— tools/build_dsl.py が生成\n"
        "# 質問(qa)/登録(register)/一括取り込み(bulk)/重複整理(dedup)/承認待ち確認(pending)\n"
        "# を LLM意図分類 + 決定的サニタイズで 1 入口に統合。設計: docs/unified-chat-design.md。\n"
        "# **直接編集せず、元 DSL とスクリプトを直して再生成する。**\n"
        "#\n"
        "# インポート後に環境へ合わせる箇所:\n"
        "#  - LLM ノードのモデル（既定は登録フローと同一。任意の LLM に差し替え可）\n"
        "#  - q_knowledge_retrieval / similar_search の dataset_ids と Reranker 設定\n"
        "#  - environment_variables の DOCSTORE_URL / DOCSTORE_API_KEY\n"
    )
    OUT.write_text(header + yaml.dump(dsl, allow_unicode=True, sort_keys=False))
    n = len(dsl["workflow"]["graph"]["nodes"])
    e = len(dsl["workflow"]["graph"]["edges"])
    print(f"OK: {OUT.name} を生成（nodes={n}, edges={e}）")


if __name__ == "__main__":
    main()
