"""按前端真实行为复现：每轮都回传累积的 messages。

useGeoAgent.ts 会传 appendHumanMessage(queryText) 的结果，
即完整对话历史。这里模拟同样行为，并检查工具是否还能调用。
"""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")

SID = f"multiturn-msg-{int(time.time())}"


def payload(q, messages, layers=None, results=None):
    return {
        "query": q,
        "messages": messages,
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
    "统计一下现在有多少个图层",
    "查一下数据库里有哪些空间表",
    "把广东省的行政边界也加载进来",
    "现在一共有几个图层",
]

messages, layers, results = [], [], []
print(f"session: {SID}\n")
for i, q in enumerate(TURNS, 1):
    # 关键：模拟前端，把用户消息累积进 messages 一起发
    messages = messages + [{"type": "human", "content": q}]
    t0 = time.time()
    tools, final, err = post(payload(q, messages, layers, results))
    dt = time.time() - t0

    new_msgs = (final or {}).get("messages") or []
    new_layers = (final or {}).get("geodata_layers") or []
    new_results = (final or {}).get("geodata_results") or []
    ans = str((new_msgs or [{}])[-1].get("content", ""))

    print(f"--- 第 {i} 轮 ({dt:.1f}s) ---")
    print(f"  Q: {q}")
    print(f"  发送 messages 条数: {len(messages)}")
    print(f"  工具: {tools or '(无) ← 异常)'}")
    print(f"  err={err}")
    print(f"  A: {ans[:150]}")

    # 用后端返回的完整历史作为下一轮输入（更贴近前端回填）
    if new_msgs:
        messages = new_msgs
    layers = new_layers or layers
    results = new_results or results
