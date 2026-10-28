"""GeoAgent Agent 地理能力实测运行器。

对 live 后端发送真实问题，记录：
  - 工具调用链（名称 + 参数）
  - 最终回答文本
  - geodata 产物（图层/结果数量、标题、类型）
  - 耗时
并按 cases_live.json 的规则自动判定。

用法：
    python run_live_eval.py                 # 跑全部
    python run_live_eval.py --only G01,P01  # 只跑指定题
    python run_live_eval.py --out results.json --timeout 300
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

API = "http://localhost:8000/api/chat"
HERE = Path(__file__).resolve().parent
CASES_PATH = HERE / "cases_live.json"
RESULTS_PATH = HERE / "results_live.json"

# 注册表 key -> LangChain 实际暴露的 tool.name。
# 题库按注册表 key 书写（更稳定），判定时映射到运行时真实名称。
TOOL_NAME_MAP: Dict[str, str] = {
    "create_execution_plan": "create_execution_plan",
    "search_metadata": "metadata_search",
    "list_user_layers": "list_user_layers",
    "geocode_nominatim": "geocode_using_nominatim_to_geostate",
    "geocode_overpass": "geocode_using_overpass_to_geostate",
    "list_postgis_layers": "list_postgis_layers",
    "load_postgis_layer": "load_postgis_layer",
    "get_custom_geoserver_data": "get_custom_geoserver_data",
    "attribute_tool": "attribute_tool",
    "attribute_tool2": "attribute_tool2",
    "geoprocess": "geoprocess_tool",
    "get_inefficient_presets": "get_inefficient_presets",
    "infer_inefficient_field_mapping": "infer_inefficient_field_mapping",
    "analyze_inefficient_space": "analyze_inefficient_space_tool",
    "style_layers": "style_map_layers",
    "autostyle_new_layers": "auto_style_new_layers",
    "check_and_autostyle": "check_and_auto_style_layers",
    "apply_color_scheme": "apply_intelligent_color_scheme",
    "world_bank_indicators": "get_world_bank_data",
    "ecmwf_weather": "get_ecmwf_weather_data",
    "nasa_fire_data": "get_nasa_fire_data",
    "nasa_gibs_layer": "get_nasa_gibs_layer",
    "list_nasa_gibs_layers": "list_nasa_gibs_layers",
    "run_python_analysis": "run_python_analysis",
}


def resolve_tool(key: str) -> str:
    """把题库里的工具 key 解析成运行时 tool.name。"""
    return TOOL_NAME_MAP.get(key, key)


def build_payload(
    query: str,
    session_id: str,
    plan_mode: bool = False,
    *,
    messages: Optional[List[Dict[str, Any]]] = None,
    geodata_layers: Optional[List[Dict[str, Any]]] = None,
    geodata_last_results: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a /chat request mirroring what the frontend sends.

    The real frontend (``useGeoAgent.ts``) resends accumulated conversation
    state each turn: ``messages`` plus ``geodata_layers`` (layers on the map) and
    ``geodata_last_results`` (the previous turn's result list). Multi-turn cases
    must do the same, otherwise the agent legitimately sees an empty session.
    """
    return {
        "query": query,
        "messages": messages or [],
        "geodata_layers": geodata_layers or [],
        "geodata_last_results": geodata_last_results or [],
        "options": {
            "session_id": session_id,
            "conversation_id": session_id,
            "geoserver_backends": [],
            "tools": [],
            "model_settings": {
                "model_provider": "vllm",
                "model_name": "Qwen3.8-27B",
                "max_tokens": 4096,
                "plan_mode": plan_mode,
                "enable_agent_audit": False,
                "enable_memory": False,
                "enable_short_term_memory": False,
                "enable_long_term_memory": False,
            },
        },
    }


def extract_tool_calls(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从消息里抽出所有 tool_calls（含参数与对应工具返回）。"""
    calls: List[Dict[str, Any]] = []
    for msg in data.get("messages") or []:
        for tc in (msg.get("additional_kwargs") or {}).get("tool_calls") or []:
            calls.append(
                {
                    "name": tc.get("name") or (tc.get("function") or {}).get("name"),
                    "args": tc.get("args") or (tc.get("function") or {}).get("arguments"),
                }
            )
    return calls


def extract_tool_outputs(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """工具返回消息（type=tool）。"""
    out = []
    for msg in data.get("messages") or []:
        if msg.get("type") == "tool":
            out.append(
                {
                    "name": msg.get("name"),
                    "content": str(msg.get("content") or "")[:1500],
                }
            )
    return out


def final_answer(data: Dict[str, Any]) -> str:
    ais = [m for m in (data.get("messages") or []) if m.get("type") == "ai"]
    return str(ais[-1].get("content") or "") if ais else ""


# ---------------------------------------------------------------- 判定

CLARIFY_MARKERS = ("？", "?", "请问", "能否", "哪个", "哪个城市", "范围", "请指定", "请告诉")


def looks_like_clarification(answer: str, tool_count: int) -> bool:
    """粗略判断回答是否在提问澄清（而非执行）。

    ``tool_count`` 只应传入「实质操作」类工具的调用数：先查一下地图状态
    再向用户澄清，仍然是澄清行为。
    """
    if tool_count > 0:
        return False
    return any(m in answer for m in CLARIFY_MARKERS)


FAKE_SUCCESS_MARKERS = ("已成功加载", "加载成功", "已完成", "已生成")
FAILURE_MARKERS = ("失败", "不存在", "没有找到", "错误", "无法", "找不到", "未找到")


def judge(case: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    """按题库规则判定，返回 {passed, score, checks, failures}。"""
    tool_names = [c["name"] for c in record["tool_calls"]]
    answer = record["final_answer"]
    checks: List[str] = []
    failures: List[str] = []

    # 1) 期望工具必须全部出现（题库用注册表 key，这里解析成运行时名称）
    for want_key in case.get("expect_tools") or []:
        want = resolve_tool(want_key)
        if want in tool_names:
            checks.append(f"✓ 调用了期望工具 {want_key}")
        else:
            failures.append(f"✗ 缺少期望工具 {want_key}（实际: {tool_names}）")

    # 2) 禁止工具不得出现
    for bad_key in case.get("forbid_tools") or []:
        bad = resolve_tool(bad_key)
        if bad in tool_names:
            failures.append(f"✗ 误用禁止工具 {bad_key}")
        else:
            checks.append(f"✓ 未误用 {bad_key}")

    # 3) 是否要求有工具调用
    #    仅"查询状态"类工具（list_user_layers / list_postgis_layers）在要求
    #    零工具调用的澄清类题目中被允许：Agent 先确认地图上有什么再澄清，
    #    是合理行为，不算空跑或误操作。
    STATE_ONLY_TOOLS = {"list_user_layers", "list_postgis_layers"}
    substantive = [n for n in tool_names if n not in STATE_ONLY_TOOLS]

    if case.get("expect_any_tool") is True and not tool_names:
        failures.append("✗ 完全未调用任何工具（怀疑空跑/编造）")
    elif case.get("expect_any_tool") is False and substantive:
        failures.append(f"✗ 本应零工具调用，实际调用了 {substantive}")
    elif case.get("expect_any_tool") is False:
        if tool_names:
            checks.append(f"✓ 仅查询状态（{tool_names}），无实质操作")
        else:
            checks.append("✓ 零工具调用符合预期")

    # 4) 产品数量
    min_gd = case.get("expect_geodata_min")
    if min_gd:
        total = record["geodata_results_count"] + record["geodata_layers_count"]
        if total >= min_gd:
            checks.append(f"✓ 产出 {total} 个地理对象（≥{min_gd}）")
        else:
            failures.append(f"✗ 地理产出不足：{total} < {min_gd}")

    # 统一定义检索文本（回答 + 工具输出），供后续多项判定复用
    haystack = (answer + " " + " ".join(o["content"] for o in record["tool_outputs"])).lower()

    # 4b) 允许配置类失败：外部服务缺 Key 时，如实报告 + 不乱用替代数据源即可
    if case.get("allow_config_error"):
        config_hit = any(
            k in haystack for k in ("api key", "apikey", "map_key", "未配置", "key 未")
        )
        if config_hit:
            checks.append("✓ 如实报告缺配置（环境问题，非能力缺陷）")
        elif record["geodata_results_count"] or record["geodata_layers_count"]:
            checks.append("✓ 已产出火点数据")

    # 5) 关键词出现在回答或工具输出中
    for kw in case.get("expect_keywords") or []:
        if kw.lower() in haystack:
            checks.append(f"✓ 命中关键词 {kw}")
        else:
            failures.append(f"✗ 回答/工具输出未提及 {kw}")

    # 6) 澄清行为（只要求没有「实质操作」，查状态不算执行）
    if case.get("expect_clarification"):
        if looks_like_clarification(answer, len(substantive)):
            checks.append("✓ 提出了澄清问题")
        else:
            failures.append(
                f"✗ 未提出澄清问题（实质工具调用={substantive or '无'}）"
            )

    # 7) 不许假装成功
    #    判定依据是「是否真有新产物」，而不是它在哪个字段。工具产出写入
    #    geodata_results 是本仓库的既有行为（只有 load_postgis_layer 会同时
    #    写 geodata_layers），所以只要有新图层/结果就不算编造。
    if case.get("expect_no_fake_success"):
        hit_fail = any(m in haystack for m in FAILURE_MARKERS)
        claims_ok = any(m in answer for m in FAKE_SUCCESS_MARKERS)
        produced = record["geodata_results_count"] + record["geodata_layers_count"]
        fallback_worked = any(
            "GeoAgentPythonAnalysis" in str(x.get("data_source") or "")
            for x in record.get("geodata_results_brief") or []
        )
        if claims_ok and produced == 0:
            failures.append("✗ 声称成功但无任何地理产物")
        elif hit_fail and claims_ok and not fallback_worked:
            failures.append("✗ 既报错又声称成功，自相矛盾")
        elif produced > 0:
            checks.append(f"✓ 声称成功且有 {produced} 个实际产物")
        else:
            checks.append("✓ 失败/成功表述一致")

    # 8) 字段探查行为
    if case.get("expect_field_discovery"):
        joined = " ".join(tool_names).lower()
        sniff = any(k in joined for k in ("attribute", "python_analysis", "search_metadata"))
        has_field_talk = any(
            k in haystack for k in ("字段", "列", "属性名", "field", "column")
        )
        if sniff or has_field_talk:
            checks.append("✓ 有字段探查迹象")
        else:
            failures.append("✗ 未见字段探查，疑似盲猜字段名")

    passed = not failures
    # 得分：满分 weight，按失败数扣分，最低 0
    weight = int(case.get("weight") or 2)
    score = max(0, weight - len(failures)) if passed else max(0, weight - len(failures) - 1)
    return {"passed": passed, "score": score, "weight": weight,
            "checks": checks, "failures": failures}


# ---------------------------------------------------------------- 主流程

def run_case(case: Dict[str, Any], timeout: int, mode: str = "stream") -> Dict[str, Any]:
    session_id = f"eval-{case['id'].lower()}-{uuid.uuid4().hex[:8]}"

    # 前置轮次：同一 session 内先跑 setup 问题，逐轮累积并回传会话状态，
    # 模拟前端的真实行为（useGeoAgent.ts 每轮发送
    # messages + geodata_layers + geodata_last_results）。
    setup_records: List[Dict[str, Any]] = []
    conv_messages: List[Dict[str, Any]] = []
    carried_layers: List[Dict[str, Any]] = []
    carried_results: List[Dict[str, Any]] = []
    for idx, setup_query in enumerate(case.get("setup") or [], 1):
        sp = build_payload(
            setup_query,
            session_id,
            plan_mode=bool(case.get("plan_mode")),
            messages=list(conv_messages),
            geodata_layers=carried_layers,
            geodata_last_results=carried_results,
        )
        st = time.time()
        sdata = None
        serr = None
        try:
            if mode == "stream":
                sdata, serr = _post_stream(sp, timeout)
            else:
                sr = requests.post(API, json=sp, timeout=timeout)
                sdata, serr = (
                    (sr.json(), None) if sr.status_code == 200 else (None, sr.text[:500])
                )
        except Exception as exc:  # noqa: BLE001
            serr = f"{type(exc).__name__}: {exc}"

        new_layers = list((sdata or {}).get("geodata_layers") or [])
        new_results = list((sdata or {}).get("geodata_results") or [])
        setup_records.append(
            {
                "query": setup_query,
                "elapsed_sec": round(time.time() - st, 2),
                "error": serr,
                "layers": len(new_layers),
                "results": len(new_results),
            }
        )
        # 累积供下一轮使用的状态。
        # 注意：只回传 geodata_layers / geodata_last_results，不回传 messages。
        # 服务端 normalize_messages() 会丢弃 ToolMessage（见 api/nalamap.py），
        # 若把带 tool_calls 的 AIMessage 连同其缺失的 ToolMessage 一起回传，
        # 会触发 "tool_calls without corresponding ToolMessage" 校验错误，
        # 这是测试脚手架的问题，不是产品行为。
        carried_layers = new_layers or carried_layers
        carried_results = new_results or carried_results

    payload = build_payload(
        case["query"],
        session_id,
        plan_mode=bool(case.get("plan_mode")),
        messages=[],
        geodata_layers=carried_layers,
        geodata_last_results=carried_results,
    )

    record: Dict[str, Any] = {
        "id": case["id"],
        "category": case.get("category"),
        "skill": case.get("skill"),
        "query": case["query"],
        "setup": setup_records or None,
        "session_id": session_id,
        "endpoint": "/api/chat/stream" if mode == "stream" else "/api/chat",
        "http_status": None,
        "elapsed_sec": None,
        "error": None,
        "tool_calls": [],
        "tool_outputs": [],
        "final_answer": "",
        "results_title": None,
        "geodata_results_count": 0,
        "geodata_layers_count": 0,
        "geodata_results_brief": [],
        "geodata_layers_brief": [],
    }

    start = time.time()
    try:
        if mode == "stream":
            data, err = _post_stream(payload, timeout)
        else:
            resp = requests.post(API, json=payload, timeout=timeout)
            record["http_status"] = resp.status_code
            if resp.status_code != 200:
                data, err = None, resp.text[:1000]
            else:
                data, err = resp.json(), None
        record["elapsed_sec"] = round(time.time() - start, 2)
        if err:
            record["error"] = err
        elif data is not None:
            record["http_status"] = record["http_status"] or 200
            if data.get("_sse_tool_calls") is not None:
                # 流式：工具链来自 SSE tool_start 事件，缺失参数时回退到消息里的 tool_calls
                sse_calls = data["_sse_tool_calls"]
                msg_calls = extract_tool_calls(data)
                merged_calls = []
                for idx, sc in enumerate(sse_calls):
                    args = sc.get("args")
                    if not args and idx < len(msg_calls):
                        args = msg_calls[idx].get("args")
                    merged_calls.append({"name": sc.get("name"), "args": args})
                record["tool_calls"] = merged_calls
                record["tool_outputs"] = data["_sse_tool_outputs"] or extract_tool_outputs(data)
            else:
                record["tool_calls"] = extract_tool_calls(data)
                record["tool_outputs"] = extract_tool_outputs(data)
            record["final_answer"] = final_answer(data)
            record["results_title"] = data.get("results_title")
            gr = data.get("geodata_results") or []
            gl = data.get("geodata_layers") or []
            record["geodata_results_count"] = len(gr)
            record["geodata_layers_count"] = len(gl)
            record["geodata_results_brief"] = [
                {
                    "title": x.get("title"),
                    "layer_type": x.get("layer_type"),
                    "data_source": x.get("data_source"),
                }
                for x in gr[:8]
            ]
            record["geodata_layers_brief"] = [
                {"title": x.get("title"), "layer_type": x.get("layer_type")}
                for x in gl[:8]
            ]
    except Exception as exc:  # noqa: BLE001
        record["elapsed_sec"] = round(time.time() - start, 2)
        record["error"] = f"{type(exc).__name__}: {exc}"

    if record["error"]:
        record["verdict"] = {
            "passed": False, "score": 0, "weight": int(case.get("weight") or 2),
            "checks": [], "failures": [f"✗ 请求失败: {record['error'][:200]}"],
        }
    else:
        record["verdict"] = judge(case, record)
    return record


def _post_stream(payload: Dict[str, Any], timeout: int) -> tuple:
    """消费 SSE 流，返回与 /chat 响应同构的 dict。"""
    tool_calls: List[Dict[str, Any]] = []
    tool_outputs: List[Dict[str, Any]] = []
    final: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    with requests.post(
        "http://localhost:8000/api/chat/stream",
        json=payload,
        stream=True,
        timeout=timeout,
    ) as resp:
        if resp.status_code != 200:
            return None, resp.text[:1000]
        event = None
        for raw in resp.iter_lines(decode_unicode=False):
            if raw is None:
                continue
            line = raw.decode("utf-8", errors="replace")
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if event == "tool_start":
                    tool_calls.append({"name": data.get("tool"), "args": data.get("input")})
                elif event == "tool_end":
                    tool_outputs.append(
                        {
                            "name": data.get("tool"),
                            "content": str(data.get("output_preview") or "")[:1500],
                        }
                    )
                elif event == "result":
                    final = data
                elif event == "error":
                    error = json.dumps(data, ensure_ascii=False)[:500]

    if error:
        return None, error
    if not final:
        return None, "stream ended without result event"

    # 把 SSE 结构转换成 /chat 的结构，复用 judge()
    messages = final.get("messages") or []
    merged = []
    for msg in messages:
        merged.append(msg)
    return (
        {
            "messages": merged,
            "results_title": final.get("results_title"),
            "geodata_results": final.get("geodata_results") or [],
            "geodata_layers": final.get("geodata_layers") or [],
            "_sse_tool_calls": tool_calls,
            "_sse_tool_outputs": tool_outputs,
        },
        None,
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="逗号分隔的题目 id")
    parser.add_argument("--out", default=str(RESULTS_PATH))
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument(
        "--mode",
        default="stream",
        choices=["stream", "blocking"],
        help="stream=生产路径 /chat/stream（默认）；blocking=/chat 非流式",
    )
    args = parser.parse_args(argv)

    cases_doc = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = cases_doc["cases"]
    if args.only:
        wanted = {s.strip() for s in args.only.split(",") if s.strip()}
        cases = [c for c in cases if c["id"] in wanted]

    records = []
    for idx, case in enumerate(cases, 1):
        print(f"[{idx}/{len(cases)}] {case['id']} {case['category']} ... ", end="", flush=True)
        rec = run_case(case, args.timeout, mode=args.mode)
        v = rec["verdict"]
        mark = "PASS" if v["passed"] else "FAIL"
        print(f"{mark} ({rec['elapsed_sec']}s, tools={[c['name'] for c in rec['tool_calls']]})")
        records.append(rec)

    total_w = sum(r["verdict"]["weight"] for r in records)
    got_s = sum(r["verdict"]["score"] for r in records)
    passed = sum(1 for r in records if r["verdict"]["passed"])

    summary = {
        "suite": cases_doc.get("suite"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "api": API,
        "total_cases": len(records),
        "passed": passed,
        "failed": len(records) - passed,
        "pass_rate": round(passed / len(records), 4) if records else 0.0,
        "score": got_s,
        "max_score": total_w,
        "score_rate": round(got_s / total_w, 4) if total_w else 0.0,
        "avg_elapsed_sec": round(
            sum(r["elapsed_sec"] or 0 for r in records) / len(records), 2
        )
        if records
        else 0.0,
    }

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print(f"通过 {passed}/{len(records)}  加权得分 {got_s}/{total_w} "
          f"({summary['score_rate'] * 100:.1f}%)")
    print(f"结果已写入 {out_path}")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
