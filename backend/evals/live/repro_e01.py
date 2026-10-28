"""单独复现 E01：验证 NASA 火点题是否稳定触发工具死循环。"""
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


for attempt, q in enumerate(
    [
        "看看北京最近有没有火点。",
        "查询 NASA FIRMS 卫星火点数据，范围是北京市，最近 3 天。",
    ],
    1,
):
    print("=" * 60)
    print(f"[attempt {attempt}] {q}")
    tools, final, err = [], None, None
    start = time.time()
    try:
        with requests.post(
            "http://localhost:8000/api/chat/stream",
            json=payload(q, f"e01-repro-{attempt}"),
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
                    elif event == "error":
                        err = data
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"

    print(f"  elapsed={time.time() - start:.1f}s")
    print(f"  tool_calls={len(tools)}")
    from collections import Counter

    print(f"  breakdown={dict(Counter(tools))}")
    print(f"  error={err}")
    if final:
        print(f"  results={len(final.get('geodata_results') or [])}")
        print(f"  answer={str((final.get('messages') or [{}])[-1].get('content', ''))[:300]}")
