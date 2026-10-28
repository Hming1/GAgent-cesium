"""复现「获取数据超出预定范围」问题。

构造几种带明确空间约束的请求，检查实际返回的 bounding_box / 要素数
是否真的落在用户指定范围内。
"""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")


def payload(q: str, sid: str) -> dict:
    return {
        "query": q,
        "messages": [],
        "options": {
            "session_id": sid,
            "conversation_id": sid,
            "geoserver_backends": [],
            "tools": [],
            "model_settings": {
                "model_provider": "vllm",
                "model_name": "Qwen3.8-27B",
                "max_tokens": 4096,
                "plan_mode": False,
                "enable_agent_audit": False,
                "enable_memory": False,
                "enable_short_term_memory": False,
            },
        },
    }


def run(q: str, tag: str) -> None:
    print("=" * 70)
    print(f"[{tag}] {q}")
    tools = []
    final = None
    start = time.time()
    try:
        with requests.post(
            "http://localhost:8000/api/chat/stream",
            json=payload(q, f"scope-{tag}-{int(time.time())}"),
            stream=True,
            timeout=600,
        ) as resp:
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
                        tools.append((data.get("tool"), data.get("input")))
                    elif event == "result":
                        final = data
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: {type(exc).__name__}: {exc}")
        return

    print(f"  耗时 {time.time() - start:.1f}s")
    print("  工具调用:")
    for name, inp in tools:
        print(f"    - {name}")
        if isinstance(inp, dict):
            for k in (
                "query", "location_name", "radius_meters", "max_results",
                "amenity_key", "bbox", "require_boundary", "maxRows",
            ):
                if k in inp:
                    print(f"        {k} = {json.dumps(inp[k], ensure_ascii=False)[:80]}")
    results = (final or {}).get("geodata_results") or []
    print(f"  结果数: {len(results)}")
    for r in results[:4]:
        print(f"    · {r.get('title')}")
        print(f"      data_source_id: {r.get('data_source_id')}")
        bb = r.get("bounding_box")
        if bb:
            print(f"      bounding_box: {str(bb)[:150]}")
    msgs = (final or {}).get("messages") or []
    if msgs:
        print(f"  回答: {str(msgs[-1].get('content',''))[:280]}")


CASES = [
    ("A-半径约束", "以北京天安门为中心，找 500 米范围内的医院。只要这个范围内的。"),
    ("B-行政范围", "只要深圳市范围内的中学，不要深圳以外任何地方的。"),
    ("C-数量上限", "给我 10 个上海的星巴克门店，只要 10 个，不要更多。"),
    ("D-省域限定", "只查广东省内的大学，别的省份一律不要。"),
]

for tag, q in CASES:
    run(q, tag)
