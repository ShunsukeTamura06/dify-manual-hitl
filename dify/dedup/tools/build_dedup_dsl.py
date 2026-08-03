"""dedup-bot.yml に「承認→統合→退役」の実行フローを合成する。

提示まで（start→…→build→format→answer）だった dedup-bot に、承認語を含むターンで
高確信クラスタを実際に統合・退役する execute 分岐を追加する。会話変数は使わず、実行
ターンで再検出する（検出は決定的なので冪等。統合済みは再検出で候補に挙がらない）。

統合直後に**完全性チェック**（execution.check_completeness と同じロジック）を挟み、
元ページの主張が統合本文から欠落していそうなら、統合先ページ本文の冒頭に警告バナーを
埋め込む（人が GROWI で公開前に確認する場所に直接出すのが最も効果的。ハードなゲートに
はせず、最終判断は人に委ねる＝HITL）。

決定的ロジックの真実は dify/dedup/dedup/（clustering.py / execution.py）とそのテスト。
本スクリプトはそれと同じロジックを Dify Code ノードにインライン展開する（既存 build
ノードが clustering をインラインしているのと同じ方式。dedup-design.md 参照）。

使い方:
    cd dify/dedup
    uv run --with pyyaml python tools/build_dedup_dsl.py
    → dify/workflows/dedup-bot.yml を更新
"""

import copy
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
DSL = REPO / "dify" / "workflows" / "dedup-bot.yml"

# ── インライン Code（実行フェーズ）。execution.py と同じロジック ──

DECIDE_CODE = '''
import difflib

_APPROVAL_KEYWORDS = ("承認", "統合して", "統合する", "実行", "まとめて", "ok", "はい")


def _is_approval(query):
    q = (query or "").strip().lower()
    return bool(q) and any(k in q for k in _APPROVAL_KEYWORDS)


def _prepare_jobs(proposals, pages):
    by_id = {str(p.get("id", "")): p for p in (pages or [])}
    jobs = []
    for prop in proposals or []:
        if prop.get("lane") != "bulk":
            continue
        page_ids = [str(i) for i in prop.get("page_ids", [])]
        members = [by_id[i] for i in page_ids if i in by_id]
        if len(members) < 2:
            continue
        rep_id = str(prop.get("representative_id", ""))
        if rep_id not in by_id:
            rep = max(members, key=lambda m: len(str(m.get("content", ""))))
            rep_id = str(rep.get("id", ""))
        rep = by_id[rep_id]
        merge_input = "\\n\\n".join(
            "## " + str(m.get("title", "")) + "\\n" + str(m.get("content", "")) for m in members
        )
        jobs.append({
            "representative_id": rep_id,
            "representative_path": str(rep.get("path", "")),
            "representative_title": str(rep.get("title", "")),
            "merge_input": merge_input,
            "member_contents": [str(m.get("content", "")) for m in members],
            "deprecated_ids": [i for i in page_ids if i != rep_id and i in by_id],
        })
    return jobs


def main(query, proposals, pages) -> dict:
    approved = _is_approval(query)
    jobs = _prepare_jobs(proposals or [], pages or []) if approved else []
    mode = "execute" if (approved and jobs) else "propose"
    return {"mode": mode, "jobs": jobs, "count": len(jobs)}
'''

UNPACK_CODE = '''
def main(item: dict) -> dict:
    item = item or {}
    return {
        "merge_input": str(item.get("merge_input", "")),
        "representative_id": str(item.get("representative_id", "")),
        "representative_path": str(item.get("representative_path", "")),
        "representative_title": str(item.get("representative_title", "")),
        "member_contents": item.get("member_contents", []),
        "deprecated_ids": item.get("deprecated_ids", []),
    }
'''

# execution.check_completeness と同じロジック（Code ノードにインライン展開）。
# 元ページの主張が統合本文から欠落していないかを機械チェックする（HITL の補助シグナル）。
CHECK_COMPLETENESS_CODE = '''
import difflib

COMPLETENESS_THRESHOLD = 0.7


def _norm(text):
    return " ".join((text or "").split())


def _best_window_ratio(haystack, needle):
    n = len(needle)
    if n == 0 or len(haystack) < n:
        return 0.0
    best = 0.0
    step = max(1, n // 4)
    for start in range(0, len(haystack) - n + 1, step):
        r = difflib.SequenceMatcher(None, needle, haystack[start:start + n]).ratio()
        if r > best:
            best = r
            if best >= 0.95:
                break
    return best


def _contains(haystack_norm, line_norm):
    if line_norm in haystack_norm:
        return True
    ratio = difflib.SequenceMatcher(None, line_norm, haystack_norm).ratio()
    return ratio >= 0.6 or _best_window_ratio(haystack_norm, line_norm) >= 0.8


def main(merged_content: str, member_contents) -> dict:
    norm_merged = _norm(merged_content)
    warnings = []
    worst = 1.0
    for idx, content in enumerate(member_contents or []):
        lines = [_norm(ln) for ln in (content or "").splitlines() if _norm(ln)]
        signif = [ln for ln in lines if len(ln) >= 4 and ln not in ("---",)]
        if not signif:
            continue
        present = sum(1 for ln in signif if _contains(norm_merged, ln))
        coverage = present / len(signif)
        worst = min(worst, coverage)
        if coverage < COMPLETENESS_THRESHOLD:
            warnings.append(f"元ページ{idx + 1}: 内容の{round(coverage * 100)}%程度しか統合本文に見当たりません")
    return {"ok": 0 if warnings else 1, "coverage": round(worst, 3), "warnings": warnings}
'''

# 統合本文を upsert ボディにする。status は決定的に draft を強制（人が再確認して公開）。
# 完全性チェックで欠落の疑いがあれば、本文冒頭（frontmatter の直後）に警告バナーを挿入する。
BUILD_MERGEBODY_CODE = '''
import json


def main(
    target_page_id: str, path: str, title: str, content: str,
    completeness_ok, completeness_warnings,
) -> dict:
    completeness_ok = bool(completeness_ok)
    lines = content.split("\\n")
    if lines and lines[0].strip() == "---":
        try:
            end = lines[1:].index("---") + 1
        except ValueError:
            end = -1
        if end > 0:
            fm = [ln for ln in lines[1:end] if not ln.strip().startswith("status:")]
            fm.append("status: draft")
            content = "\\n".join(["---"] + fm + lines[end:])
    else:
        content = "---\\nstatus: draft\\n---\\n" + content

    if not completeness_ok:
        detail = "\\n".join(f"> - {w}" for w in (completeness_warnings or []))
        banner = (
            "> ⚠️ **完全性チェック警告**: 統合元ページの内容が一部欠落している"
            "可能性があります。公開前に必ず原文と見比べてご確認ください。\\n"
            f"{detail}\\n\\n"
        )
        # frontmatter (---...---) の直後にバナーを挿入する
        lines2 = content.split("\\n")
        if lines2 and lines2[0].strip() == "---":
            try:
                end2 = lines2[1:].index("---") + 1
                content = "\\n".join(lines2[: end2 + 1]) + "\\n\\n" + banner + "\\n".join(lines2[end2 + 1:])
            except ValueError:
                content = banner + content
        else:
            content = banner + content

    body = json.dumps({
        "target_page_id": target_page_id or "",
        "path": path, "title": title,
        "content": content, "metadata": {},
    }, ensure_ascii=False)
    return {"body": body}
'''

BUILD_DEPBODY_CODE = '''
import json


def main(deprecated_ids, redirect_path: str) -> dict:
    body = json.dumps({
        "page_ids": list(deprecated_ids or []),
        "redirect_path": redirect_path or "",
    }, ensure_ascii=False)
    return {"body": body}
'''

MERGE_SYSTEM_PROMPT = (
    "複数の重複ページを 1 つに統合したマニュアル本文を作る。\n"
    "- **全ページの主張を保持**する。要約で情報を落とさない（欠落は最も避けるべき失敗）。\n"
    "- 重複する記述は 1 つにまとめる。矛盾する記述は両方残し、どちらが新しい/正しいか"
    "確認を促す注記を付ける。\n"
    "- frontmatter を含む Markdown 本文そのものだけを出力。``` で囲まない。"
    "status は書かない（後段が draft を設定する）。"
)


def _node(nid, ntype, title, extra, x, y, parent=None):
    data = {"type": ntype, "title": title}
    data.update(extra)
    if parent:
        data["isInIteration"] = True
        data["iteration_id"] = parent
    # 外側の type は通常 "custom" だが、iteration-start ノードだけは
    # Dify のキャンバス描画が別コンポーネントとして扱うため
    # "custom-iteration-start" でなければならない（Reactのレンダリングが壊れる）。
    outer_type = "custom-iteration-start" if ntype == "iteration-start" else "custom"
    node = {"data": data, "id": nid, "position": {"x": x, "y": y}, "type": outer_type}
    if parent:
        node["parentId"] = parent
        node["zIndex"] = 1002
    return node


def _edge(source, target, handle="source", in_iter=False, iter_id=None):
    e = {
        "id": f"{source}-{handle}-{target}",
        "source": source,
        "sourceHandle": handle,
        "target": target,
        "targetHandle": "target",
        "type": "custom",
        "data": {"isInIteration": in_iter},
    }
    if in_iter and iter_id:
        e["data"]["iteration_id"] = iter_id
        e["zIndex"] = 1002
    return e


def build() -> dict:
    dsl = yaml.safe_load(DSL.read_text())
    graph = dsl["workflow"]["graph"]

    # 冪等化: 以前に生成した execute 分岐のノード/エッジを一旦すべて除去してから作り直す
    gen = {"decide", "mode_ifelse", "merge_iter", "merge_iterstart", "m_unpack",
           "m_merge_llm", "m_check", "m_build_body", "m_http_upsert", "m_dep_body",
           "m_http_deprecate", "exec_answer"}
    graph["nodes"] = [n for n in graph["nodes"] if n["id"] not in gen]
    graph["edges"] = [
        e for e in graph["edges"] if e["source"] not in gen and e["target"] not in gen
    ]
    if not any(e["source"] == "build" and e["target"] == "format" for e in graph["edges"]):
        graph["edges"].append(_edge("build", "format"))
    nodes = {n["id"]: n for n in graph["nodes"]}

    # 1) build ノード: 提案に representative_id を含め、pages も出力し、退役ページを除外する
    b = nodes["build"]["data"]
    code = b["code"]
    if '"representative_id"' not in code:
        code = code.replace(
            '"representative_title": str(rep.get("title", "")),',
            '"representative_id": str(rep.get("id", "")),\n'
            '                "representative_title": str(rep.get("title", "")),',
        )
    # 退役済み（status: deprecated）ページは検出対象から外す（統合後の再検出で再クラスタ化しない = 冪等）
    if "== \"deprecated\"" not in code:
        code = code.replace(
            '        content = cj.get("content", "") if isinstance(cj, dict) else ""\n',
            '        if isinstance(cj, dict) and cj.get("status") == "deprecated":\n'
            '            continue\n'
            '        content = cj.get("content", "") if isinstance(cj, dict) else ""\n',
        )
    # build の main が pages も返すように
    code = code.replace(
        'return {"proposals": build_proposals(pages, pairs, CANDIDATE_OVERLAP)}',
        'return {"proposals": build_proposals(pages, pairs, CANDIDATE_OVERLAP), "pages": pages}',
    )
    b["code"] = code
    b["outputs"]["pages"] = {"children": None, "type": "array[object]"}

    # 1b) format（提示）ノードの締めの文を、統合を促す案内に更新する
    f = nodes["format"]["data"]
    f["code"] = f["code"].replace(
        '"※ これは提案です。統合の実行は次段（承認→LLM統合→反映）で行います。"',
        '"※ 高確信の重複を統合するには「統合して」「実行」と送ってください"\n'
        '                 "（統合先は下書き、重複元は退役になります）。"',
    )

    # 2) decide ノード（承認判定 + 統合ジョブ組み立て）
    decide = _node(
        "decide", "code", "実行判定",
        {
            "code_language": "python3", "code": DECIDE_CODE,
            "desc": "承認語があり高確信クラスタがあれば execute。無ければ propose（提示のみ）",
            "outputs": {
                "mode": {"children": None, "type": "string"},
                "jobs": {"children": None, "type": "array[object]"},
                "count": {"children": None, "type": "number"},
            },
            "variables": [
                {"variable": "query", "value_selector": ["sys", "query"]},
                {"variable": "proposals", "value_selector": ["build", "proposals"]},
                {"variable": "pages", "value_selector": ["build", "pages"]},
            ],
        },
        x=1900, y=282,
    )

    # 3) IF/ELSE（mode）
    ifelse = _node(
        "mode_ifelse", "if-else", "モード分岐",
        {
            "desc": "execute（統合実行） / それ以外は propose（提示）",
            "cases": [{
                "case_id": "case_execute", "logical_operator": "and",
                "conditions": [{
                    "id": "cond_execute", "comparison_operator": "is",
                    "value": "execute", "varType": "string",
                    "variable_selector": ["decide", "mode"],
                }],
            }],
        },
        x=2160, y=282,
    )

    # 4) 統合 Iteration
    IT = "merge_iter"
    merge_iter = _node(
        IT, "iteration", "各クラスタを統合",
        {
            "desc": "高確信クラスタごとに: 統合本文生成 → 統合先を更新 → 重複元を退役",
            "error_handle_mode": "terminated", "is_parallel": False, "parallel_nums": 3,
            "iterator_input_type": "array[object]",
            "iterator_selector": ["decide", "jobs"],
            "output_selector": ["m_http_deprecate", "body"],
            "output_type": "array[string]",
            "start_node_id": "merge_iterstart",
            "width": 620, "height": 250,
        },
        x=2420, y=420,
    )
    it_start = _node("merge_iterstart", "iteration-start", "", {"desc": "", "isInIteration": True}, 20, 90, parent=IT)
    # iteration-start は特殊（parentId のみ、iteration_id 不要）
    it_start["data"].pop("iteration_id", None)

    unpack = _node("m_unpack", "code", "ジョブ展開",
                   {"code_language": "python3", "code": UNPACK_CODE,
                    "outputs": {k: {"children": None, "type": t} for k, t in [
                        ("merge_input", "string"), ("representative_id", "string"),
                        ("representative_path", "string"), ("representative_title", "string"),
                        ("member_contents", "array[string]"),
                        ("deprecated_ids", "array[string]")]},
                    "variables": [{"variable": "item", "value_selector": [IT, "item"]}]},
                   140, 90, parent=IT)

    merge_llm = _node("m_merge_llm", "llm", "統合本文生成",
                      {"model": copy.deepcopy(_first_llm_model(nodes)),
                       "prompt_template": [
                           {"role": "system", "text": MERGE_SYSTEM_PROMPT},
                           {"role": "user", "text": "統合対象の重複ページ群:\n\n{{#m_unpack.merge_input#}}"}],
                       "context": {"enabled": False, "variable_selector": []},
                       "vision": {"enabled": False}},
                      360, 90, parent=IT)

    check = _node("m_check", "code", "完全性チェック",
                  {"code_language": "python3", "code": CHECK_COMPLETENESS_CODE,
                   "desc": "元ページの主張が統合本文から欠落していないか機械チェック（HITLの補助）",
                   "outputs": {
                       "ok": {"children": None, "type": "number"},
                       "coverage": {"children": None, "type": "number"},
                       "warnings": {"children": None, "type": "array[string]"},
                   },
                   "variables": [
                       {"variable": "merged_content", "value_selector": ["m_merge_llm", "text"]},
                       {"variable": "member_contents", "value_selector": ["m_unpack", "member_contents"]}]},
                  480, 90, parent=IT)

    mergebody = _node("m_build_body", "code", "upsertボディ組立",
                      {"code_language": "python3", "code": BUILD_MERGEBODY_CODE,
                       "outputs": {"body": {"children": None, "type": "string"}},
                       "variables": [
                           {"variable": "target_page_id", "value_selector": ["m_unpack", "representative_id"]},
                           {"variable": "path", "value_selector": ["m_unpack", "representative_path"]},
                           {"variable": "title", "value_selector": ["m_unpack", "representative_title"]},
                           {"variable": "content", "value_selector": ["m_merge_llm", "text"]},
                           {"variable": "completeness_ok", "value_selector": ["m_check", "ok"]},
                           {"variable": "completeness_warnings", "value_selector": ["m_check", "warnings"]}]},
                      600, 90, parent=IT)

    http_upsert = _node("m_http_upsert", "http-request", "統合先を更新",
                        _http("post", "{{#env.DOCSTORE_URL#}}/pages/upsert", "{{#m_build_body.body#}}"),
                        800, 90, parent=IT)

    depbody = _node("m_dep_body", "code", "退役ボディ組立",
                    {"code_language": "python3", "code": BUILD_DEPBODY_CODE,
                     "outputs": {"body": {"children": None, "type": "string"}},
                     "variables": [
                         {"variable": "deprecated_ids", "value_selector": ["m_unpack", "deprecated_ids"]},
                         {"variable": "redirect_path", "value_selector": ["m_unpack", "representative_path"]}]},
                    1020, 90, parent=IT)

    http_dep = _node("m_http_deprecate", "http-request", "重複元を退役",
                     _http("post", "{{#env.DOCSTORE_URL#}}/pages/deprecate", "{{#m_dep_body.body#}}"),
                     1240, 90, parent=IT)

    exec_answer = _node("exec_answer", "answer", "統合完了通知",
                        {"answer": "{{#decide.count#}} 件の重複クラスタを統合しました。\n\n"
                                   "統合先は下書き（draft）にしました。GROWI で内容を確認して公開してください。\n"
                                   "重複元は退役（deprecated）にし、統合先へのリンクを付けました（検索には出ません）。\n"
                                   "※ 統合は情報の欠落が起きていないか、公開前に必ずご確認ください"
                                   "（自動チェックで欠落の疑いがあれば統合先ページ冒頭に警告を入れています）。",
                         "variables": []},
                        2680, 560)

    # 5) 既存の build→format 接続を build→decide→ifelse に張り替える
    graph["edges"] = [e for e in graph["edges"] if not (e["source"] == "build" and e["target"] == "format")]

    new_nodes = [decide, ifelse, merge_iter, it_start, unpack, merge_llm,
                 check, mergebody, http_upsert, depbody, http_dep, exec_answer]
    graph["nodes"].extend(new_nodes)
    graph["edges"].extend([
        _edge("build", "decide"),
        _edge("decide", "mode_ifelse"),
        _edge("mode_ifelse", "format", handle="false"),         # propose（既定）
        _edge("mode_ifelse", "merge_iter", handle="case_execute"),
        _edge("merge_iter", "exec_answer"),
        # iteration 内部
        _edge("merge_iterstart", "m_unpack", in_iter=True, iter_id=IT),
        _edge("m_unpack", "m_merge_llm", in_iter=True, iter_id=IT),
        _edge("m_merge_llm", "m_check", in_iter=True, iter_id=IT),
        _edge("m_check", "m_build_body", in_iter=True, iter_id=IT),
        _edge("m_build_body", "m_http_upsert", in_iter=True, iter_id=IT),
        _edge("m_http_upsert", "m_dep_body", in_iter=True, iter_id=IT),
        _edge("m_dep_body", "m_http_deprecate", in_iter=True, iter_id=IT),
    ])

    # opening_statement を実行できる旨に更新
    dsl["workflow"]["features"]["opening_statement"] = (
        "重複ページの整理を手伝います。\n"
        "・確認: 「/manuals/… の重複を整理して」→ 重複候補を提示します\n"
        "・統合: 「統合して」「実行」→ 高確信の重複を実際に統合し、重複元を退役します\n"
        "統合先は下書きになり、GROWI で公開すると反映されます。"
    )
    return dsl


def _first_llm_model(nodes):
    for n in nodes.values():
        if n["data"].get("type") == "llm":
            return n["data"]["model"]
    # dedup-bot に LLM が無ければ OpenAI 既定
    return {"provider": "langgenius/openai/openai", "name": "gpt-4o-mini",
            "mode": "chat", "completion_params": {"temperature": 0.2, "max_tokens": 4000}}


def _http(method, url, body):
    return {
        "authorization": {"config": None, "type": "no-auth"},
        "body": {"data": body, "type": "raw-text"},
        "headers": "Content-Type:application/json\nX-API-Key:{{#env.DOCSTORE_API_KEY#}}",
        "method": method, "params": "",
        "timeout": {"max_connect_timeout": 10, "max_read_timeout": 60, "max_write_timeout": 60},
        "url": url,
    }


def main() -> None:
    dsl = build()
    header = (
        "# 重複排除Bot — dify/dedup/tools/build_dedup_dsl.py が生成（提示→承認→統合→退役）\n"
        "# 決定的ロジックの真実は dify/dedup/（clustering.py / execution.py）とテスト。\n"
        "# 一覧取得(http_list)・フィルタ(parse_list)・提案整形(build/format)は\n"
        "# build_dedup_dsl.py の管理外（このファイルを直接編集する）。\n"
        "# インポート後: environment_variables の DOCSTORE_URL / DOCSTORE_API_KEY、LLM モデル。\n"
    )
    DSL.write_text(header + yaml.dump(dsl, allow_unicode=True, sort_keys=False))
    n = len(dsl["workflow"]["graph"]["nodes"])
    e = len(dsl["workflow"]["graph"]["edges"])
    print(f"OK: dedup-bot.yml を生成（nodes={n}, edges={e}）")


if __name__ == "__main__":
    main()
