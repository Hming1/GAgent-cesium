"""汇总最终回归结果，生成 Markdown 表格供文档引用。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
path = HERE / "results_final.json"
data = json.loads(path.read_text(encoding="utf-8"))
summary = data["summary"]
records = data["records"]

print("## 总体结果\n")
print("| 指标 | 数值 |")
print("|------|------|")
print(f"| 题目总数 | {summary['total_cases']} |")
print(f"| 通过 | {summary['passed']} |")
print(f"| 失败 | {summary['failed']} |")
print(f"| 通过率 | {summary['pass_rate'] * 100:.1f}% |")
print(f"| 加权得分 | {summary['score']}/{summary['max_score']} ({summary['score_rate'] * 100:.1f}%) |")
print(f"| 平均耗时 | {summary['avg_elapsed_sec']}s |")

print("\n## 逐题结果\n")
print("| 题号 | 类别 | 结果 | 耗时 | 工具链 | 得分 |")
print("|------|------|------|------|--------|------|")
for r in records:
    v = r["verdict"]
    mark = "✅ PASS" if v["passed"] else "❌ FAIL"
    tools = " → ".join(c["name"].replace("_using_nominatim_to_geostate", "")
                       .replace("_using_overpass_to_geostate", "")
                       .replace("_tool", "") for c in r["tool_calls"]) or "（无）"
    if len(tools) > 70:
        tools = tools[:67] + "..."
    print(f"| {r['id']} | {r['category']} | {mark} | {r['elapsed_sec']}s | {tools} | "
          f"{v['score']}/{v['weight']} |")

print("\n## 工具调用频次\n")
counter = Counter()
for r in records:
    for c in r["tool_calls"]:
        counter[c["name"]] += 1
print("| 工具 | 调用次数 |")
print("|------|----------|")
for name, n in counter.most_common():
    print(f"| `{name}` | {n} |")

print("\n## 产物统计\n")
tl = sum(r["geodata_layers_count"] for r in records)
tr = sum(r["geodata_results_count"] for r in records)
print(f"- geodata_layers 累计: **{tl}**")
print(f"- geodata_results 累计: **{tr}**")
print(f"- 图层/结果比: {tl}/{tr}")

print("\n## 失败题\n")
for r in records:
    if r["verdict"]["passed"]:
        continue
    print(f"### {r['id']} — {r['category']}\n")
    print(f"- 耗时: {r['elapsed_sec']}s")
    print(f"- 工具链: {[c['name'] for c in r['tool_calls']]}")
    print(f"- 失败项:")
    for f in r["verdict"]["failures"]:
        print(f"  - {f}")
    print(f"- 回答摘录: {r['final_answer'][:400]}")
    print()
