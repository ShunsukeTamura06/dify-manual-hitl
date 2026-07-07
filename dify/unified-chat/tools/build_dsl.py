"""統一チャット v1 の Chatflow DSL を既存 3 Bot の検証済み DSL から機械合成する。

手作業のコピペで参照（value_selector / iteration_id / {{#node.field#}}）を壊さないため、
ノード ID の名前空間化と参照の再配線をスクリプトで行う（docs/unified-chat-design.md）。

使い方:
    cd dify/unified-chat
    uv run --with pyyaml python tools/build_dsl.py
    → dify/workflows/unified-chat-bot.yml を生成

合成規則:
- 登録 Bot をベースに、その start / doc_extractor を共有ノードとして使う。
- QA Bot のノードは q_ 接頭辞、一括取り込み Bot のノードは b_ 接頭辞で名前空間化。
- doc_extractor の後ろに ルーター(Code) → IF/ELSE を挿入し 3 分岐する。
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

    # ── ルーター（Code・決定的）と IF/ELSE ──
    router_node = {
        "data": {
            "type": "code",
            "title": "ルーター(決定的)",
            "desc": "添付の有無・抽出文字数・明示キーワードで qa/register/bulk を決める",
            "code_language": "python3",
            "code": ROUTER_CODE,
            "outputs": {"route": {"type": "string"}},
            "variables": [
                {"variable": "query", "value_selector": ["sys", "query"]},
                {"variable": "extracted_text", "value_selector": ["doc_extractor", "text"]},
            ],
        },
        "id": "router",
        "position": {"x": 640, "y": 282},
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
                # bulk も明示 case にする。ELSE（既定）を書込系フローに向けない:
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
            ],
        },
        "id": "route_ifelse",
        "position": {"x": 900, "y": 282},
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
            ),
        },
        "id": "route_fallback_answer",
        "position": {"x": 1160, "y": 120},
        "type": "custom",
    }

    # qa 分岐の LLM は登録フローと同じモデルに揃える（dependencies と整合させるため。
    # インポート後に任意の LLM へ差し替え可能な点は変わらない）
    reg_llm_model = next(n for n in reg_nodes if n["id"] == "llm1")["data"]["model"]
    q_llm = next(n for n in qa_nodes if n["id"] == "q_llm")
    q_llm["data"]["model"] = {**q_llm["data"]["model"], **copy.deepcopy(reg_llm_model)}

    nodes = reg_nodes + qa_nodes + bulk_nodes + [router_node, ifelse_node, fallback_node]
    edges = (
        reg_edges
        + qa_edges
        + bulk_edges
        + [
            _edge("doc_extractor", "router"),
            _edge("router", "route_ifelse"),
            _edge("route_ifelse", "q_knowledge_retrieval", handle="case_qa"),
            _edge("route_ifelse", "llm1", handle="case_register"),
            _edge("route_ifelse", "b_split_windows", handle="case_bulk"),
            _edge("route_ifelse", "route_fallback_answer", handle="false"),
        ]
    )
    # エッジ ID の重複を避ける（各 Bot 由来の e1 等が衝突しうる）
    for e in edges:
        e["id"] = f"{e['source']}-{e.get('sourceHandle','source')}-{e['target']}"

    # ── アプリ全体 ──
    features = copy.deepcopy(reg["workflow"]["features"])
    features["opening_statement"] = (
        "マニュアルのことは何でもここへどうぞ。\n"
        "・質問: そのまま聞いてください（出典付きで回答します）\n"
        "・登録/更新: ファイルを添付してください（大きい文書は自動で分割します）\n"
        "登録されたページは下書きになり、GROWI で公開すると検索に反映されます。\n"
    )
    features["retriever_resource"] = {"enabled": True}

    return {
        "app": {
            "description": (
                "マニュアル統一チャット v1。質問・登録・一括取り込みを"
                " 1 つの入口で受け、決定的ルーティングで振り分ける。"
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
    return errors


def main() -> None:
    dsl = build()
    errors = validate(dsl)
    if errors:
        for e in errors:
            print("NG:", e)
        raise SystemExit(1)
    header = (
        "# マニュアルアシスタント（統一チャット v1）— tools/build_dsl.py が生成\n"
        "# 質問(qa) / 登録(register) / 一括取り込み(bulk) を決定的ルーティングで 1 入口に統合。\n"
        "# 設計: docs/unified-chat-design.md。\n"
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
