"""实测：Agent 搜索结果的完整可获得性 + 溯源信息。

验证四点：
  1. 响应里 geodata_results 是否带完整详情字段
  2. data_link 是否真能取回原始 GeoJSON
  3. 审计表是否记录了这次运行的完整工具链
  4. 溯源链（source -> tool -> 产物）是否闭合
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

QUERY = "把深圳市行政边界加载到地图上，并告诉我这个数据的来源和要素数量"
SID = f"trace-demo-{int(time.time())}"


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
                # 审计保持默认开启（前端真实行为）
                "enable_agent_audit": True,
                "agent_audit_level": "tool",
                "enable_memory": False,
                "enable_short_term_memory": False,
            },
        },
    }


tools = []
final = None
start = time.time()
with requests.post(
    "http://localhost:8000/api/chat/stream",
    json=payload(QUERY, SID),
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

print(f"=== 请求完成 {time.time() - start:.1f}s ===")
print("session_id:", SID)
print("工具链:", tools)

print("\n=== geodata_results 详情字段 ===")
results = (final or {}).get("geodata_results") or []
print(f"结果数: {len(results)}")
for r in results:
    print("\n--- 单条结果 ---")
    for key in (
        "id", "name", "title", "data_source", "data_source_id", "data_type",
        "data_origin", "data_link", "layer_type", "bounding_box", "sha256", "size",
        "score",
    ):
        if key in r:
            v = str(r.get(key))
            print(f"  {key:16s}: {v[:100]}")
    pm = r.get("processing_metadata")
    if pm:
        print("  processing_metadata:")
        print("    operation      :", pm.get("operation"))
        print("    crs_used       :", pm.get("crs_used"))
        print("    origin_layers  :", pm.get("origin_layers"))
    props = r.get("properties")
    if props:
        print("  properties     :", str(props)[:150])
    dl = r.get("data_link")
    if dl:
        print(f"\n  → 尝试取回 data_link: {dl[:90]}")
        try:
            gr = requests.get(dl, timeout=30)
            print(f"     HTTP {gr.status_code}, {len(gr.content)} bytes")
            if gr.status_code == 200:
                fc = gr.json()
                feats = fc.get("features") or []
                print(f"     GeoJSON type={fc.get('type')}, features={len(feats)}")
                if feats:
                    print("     首个要素 properties 键:",
                          list((feats[0].get("properties") or {}).keys())[:12])
                    print("     首个要素 geometry 类型:",
                          (feats[0].get("geometry") or {}).get("type"))
        except Exception as exc:  # noqa: BLE001
            print(f"     取回失败: {type(exc).__name__}: {exc}")

print("\n=== 最终回答 ===")
msgs = (final or {}).get("messages") or []
if msgs:
    print(str(msgs[-1].get("content", ""))[:800])

# 保存 session_id 供后续查审计
Path("_trace_session.txt").write_text(SID, encoding="utf-8")
