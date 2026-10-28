"""汇总 results_stream.json 的统计与失败详情，输出 UTF-8 报告。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
data = json.loads((HERE / "results_stream.json").read_text(encoding="utf-8"))
summary = data["summary"]
records = data["records"]

print("=" * 70)
print("SUMMARY")
print("=" * 70)
for key in (
    "total_cases", "passed", "failed", "pass_rate",
    "score", "max_score", "score_rate", "avg_elapsed_sec",
):
    print(f"  {key}: {summary[key]}")

print("\n" + "=" * 70)
print("失败题详情")
print("=" * 70)
for r in records:
    if r["verdict"]["passed"]:
        continue
    print(f"\n[{r['id']}] {r['category']}  elapsed={r['elapsed_sec']}s")
    if r.get("setup"):
        for s in r["setup"]:
            print(f"  setup: {s['query']} -> layers={s.get('layers')}, err={s.get('error')}")
    print(f"  tools: {[c['name'] for c in r['tool_calls']]}")
    print(f"  layers={r['geodata_layers_count']} results={r['geodata_results_count']}")
    print(f"  answer: {r['final_answer'][:700]}")
    for f in r["verdict"]["failures"]:
        print(f"  FAIL: {f}")

print("\n" + "=" * 70)
print("耗时排行")
print("=" * 70)
for r in sorted(records, key=lambda x: -(x["elapsed_sec"] or 0))[:8]:
    print(f"  {r['id']:4s} {r['elapsed_sec']:7.1f}s  tools={len(r['tool_calls']):2d}  {r['category']}")

print("\n" + "=" * 70)
print("工具调用统计")
print("=" * 70)
counter = Counter()
for r in records:
    for c in r["tool_calls"]:
        counter[c["name"]] += 1
for name, n in counter.most_common():
    print(f"  {n:3d}  {name}")

print("\n" + "=" * 70)
print("geodata_layers 产出检查（关键缺陷）")
print("=" * 70)
total_layers = sum(r["geodata_layers_count"] for r in records)
total_results = sum(r["geodata_results_count"] for r in records)
print(f"  所有题累计 geodata_layers: {total_layers}")
print(f"  所有题累计 geodata_results: {total_results}")
for r in records:
    if r["geodata_layers_count"] or r["geodata_results_count"]:
        print(f"  {r['id']:4s} layers={r['geodata_layers_count']} results={r['geodata_results_count']}")
