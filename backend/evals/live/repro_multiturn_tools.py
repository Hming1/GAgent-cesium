"""复现：同一会话中连续多轮调用工具是否正常。

现象：一次对话中只能调用一次工具，后续轮次无法调用。
"""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")

SID = f"multiturn-{int(time.time())}"


def payload(q, layers=None, results=None):
    return {
        "query": q,
        "messages": [],
        "geodata_layers": layers or [],
        "geodata_last_results": results or [],
        "options": {
            "session_id": SID,
            "conversation_id": SID,
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


def post(p):
    tools, final, err = [], None, None
    with requests.post(
        "http://localhost:8000/api/chat/stream", json=p, stream=True, timeout=600
    ) as r:
        ev = None
        for raw in r.iter_lines(decode_unicode=False):
            if raw is None:
                continue
            line = raw.decode("utf-8", "replace")
            if line.startswith("event: "):
                ev = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if ev == "tool_start":
                    tools.append(d.get("tool"))
                elif ev == "result":
                    final = d
                elif ev == "error":
                    err = d
    return tools, final, err


TURNS = [
    "把深圳市行政边界加载到地图上",
    "现在做 200 米缓冲区",
    "再把缓冲结果做一次 100 米缓冲",
    "统计一下现在有多少个图层",
    "把它们都加载出来看看",
]

layers, results = [], []
print(f"session: {SID}\n")
for i, q in enumerate(TURNS, 1):
    t0 = time.time()
    tools, final, err = post(payload(q, layers, results))
    dt = time.time() - t0
    new_layers = (final or {}).get("geodata_layers") or []
    new_results = (final or {}).get("geodata_results") or []
    ans = str(((final or {}).get("messages") or [{}])[-1].get("content", ""))

    print(f"--- 第 {i} 轮 ({dt:.1f}s) ---")
    print(f"  Q: {q}")
    print(f"  工具: {tools or '(无)'}")
    print(f"  layers={len(new_layers)} results={len(new_results)} err={err}")
    print(f"  A: {ans[:160]}")

    layers = new_layers or layers
    results = new_results or results
