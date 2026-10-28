"""S01 单轮验证：在一次请求内完成「加载边界 + 改样式」，不依赖跨轮图层。

目的：区分
  (a) style_layers 工具本身坏了  → 单轮也会失败
  (b) 只是跨轮 geodata_layers 不保留 → 单轮可成功
"""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")


def payload(query: str, sid: str) -> dict:
    return {
        "query": query,
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


QUERY = (
    "把深圳市行政边界加载出来，然后把这个边界图层填充改成蓝色、40% 透明，"
    "其它图层样式不要动。"
)

start = time.time()
tools, final = [], None
with requests.post(
    "http://localhost:8000/api/chat/stream",
    json=payload(QUERY, "s01-single-01"),
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
                tools.append(data.get("tool"))
            elif event == "result":
                final = data

print(f"elapsed={time.time() - start:.1f}s")
print("tools:", tools)
if final:
    print("results:", len(final.get("geodata_results") or []))
    print("layers:", len(final.get("geodata_layers") or []))
    print("answer:", str((final.get("messages") or [{}])[-1].get("content", ""))[:600])
