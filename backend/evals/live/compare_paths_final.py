"""对比 /chat 与 /chat/stream 的递归上限差异，生成可复现证据。"""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")

QUERY = "把深圳市行政边界加载出来，然后做 200 米缓冲区，输出成新图层，不要覆盖原来的边界。"


def payload(sid: str) -> dict:
    return {
        "query": QUERY,
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


results = {}

# 非流式
start = time.time()
try:
    r = requests.post("http://localhost:8000/api/chat", json=payload("cmp-final-blocking"), timeout=900)
    d = r.json()
    tools = [
        tc.get("name")
        for m in d.get("messages") or []
        for tc in (m.get("additional_kwargs") or {}).get("tool_calls") or []
    ]
    results["blocking"] = {
        "elapsed": round(time.time() - start, 1),
        "http": r.status_code,
        "tools": tools,
        "layers": len(d.get("geodata_layers") or []),
        "results": len(d.get("geodata_results") or []),
        "answer": str((d.get("messages") or [{}])[-1].get("content", ""))[:200],
    }
except Exception as exc:  # noqa: BLE001
    results["blocking"] = {"error": f"{type(exc).__name__}: {exc}"}

# 流式
tools, final, err = [], None, None
start = time.time()
try:
    with requests.post(
        "http://localhost:8000/api/chat/stream",
        json=payload("cmp-final-stream"),
        stream=True,
        timeout=900,
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
                    tools.append(data.get("tool"))
                elif event == "result":
                    final = data
                elif event == "error":
                    err = data
    results["stream"] = {
        "elapsed": round(time.time() - start, 1),
        "tools": tools,
        "layers": len((final or {}).get("geodata_layers") or []),
        "results": len((final or {}).get("geodata_results") or []),
        "error": err,
        "answer": str(((final or {}).get("messages") or [{}])[-1].get("content", ""))[:200],
    }
except Exception as exc:  # noqa: BLE001
    results["stream"] = {"error": f"{type(exc).__name__}: {exc}"}

print(json.dumps(results, ensure_ascii=False, indent=2))
