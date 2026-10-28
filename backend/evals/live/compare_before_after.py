"""对比修复前后的评测结果，输出 Markdown 对比表。"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent

before = json.loads((HERE / "results_baseline.json").read_text(encoding="utf-8"))
after = json.loads((HERE / "results_after.json").read_text(encoding="utf-8"))

b, a = before["summary"], after["summary"]
brecs = {r["id"]: r for r in before["records"]}
arecs = {r["id"]: r for r in after["records"]}
common = [cid for cid in arecs if cid in brecs]

print("## 总体对比\n")
print("| 指标 | 修复前 | 修复后 | 变化 |")
print("|------|--------|--------|------|")
rows = [
    ("通过题数", b["passed"], a["passed"], f"{a['passed'] - b['passed']:+d}"),
    ("通过率", f"{b['pass_rate']*100:.1f}%", f"{a['pass_rate']*100:.1f}%",
     f"{(a['pass_rate']-b['pass_rate'])*100:+.1f}pp"),
    ("加权得分", f"{b['score']}/{b['max_score']}", f"{a['score']}/{a['max_score']}",
     f"{a['score']-b['score']:+d}"),
    ("得分率", f"{b['score_rate']*100:.1f}%", f"{a['score_rate']*100:.1f}%",
     f"{(a['score_rate']-b['score_rate'])*100:+.1f}pp"),
    ("平均耗时", f"{b['avg_elapsed_sec']}s", f"{a['avg_elapsed_sec']}s",
     f"{a['avg_elapsed_sec']-b['avg_elapsed_sec']:+.1f}s"),
]
for name, bv, av, d in rows:
    print(f"| {name} | {bv} | {av} | **{d}** |")

# 图层/结果比
def totals(doc):
    tl = sum(r["geodata_layers_count"] for r in doc["records"])
    tr = sum(r["geodata_results_count"] for r in doc["records"])
    return tl, tr

btl, btr = totals(before)
atl, atr = totals(after)
print(f"| geodata_layers 累计 | {btl} | {atl} | **{atl - btl:+d}** |")
print(f"| geodata_results 累计 | {btr} | {atr} | **{atr - btr:+d}** |")

# 沙箱 / 工具调用
def tool_counts(doc):
    c = Counter()
    for r in doc["records"]:
        for t in r["tool_calls"]:
            c[t["name"]] += 1
    return c

bc, ac = tool_counts(before), tool_counts(after)
print(f"| 工具调用总数 | {sum(bc.values())} | {sum(ac.values())} | **{sum(ac.values()) - sum(bc.values()):+d}** |")
print(f"| run_python_analysis 次数 | {bc.get('run_python_analysis', 0)} | "
      f"{ac.get('run_python_analysis', 0)} | **{ac.get('run_python_analysis', 0) - bc.get('run_python_analysis', 0):+d}** |")

# 递归爆栈
def recursion_fails(doc):
    return sum(
        1 for r in doc["records"]
        if r.get("error") and "Recursion limit" in str(r.get("error"))
    )

print(f"| 递归爆栈题数 | {recursion_fails(before)} | {recursion_fails(after)} | "
      f"**{recursion_fails(after) - recursion_fails(before):+d}** |")

print("\n## 逐题对比\n")
print("| 题号 | 类别 | 修复前 | 修复后 | 耗时变化 | 工具数变化 |")
print("|------|------|--------|--------|----------|------------|")
for cid in sorted(arecs, key=lambda x: list(arecs).index(x)):
    a_r = arecs[cid]
    b_r = brecs.get(cid)
    if not b_r:
        continue
    bm = "✅" if b_r["verdict"]["passed"] else "❌"
    am = "✅" if a_r["verdict"]["passed"] else "❌"
    bt = len(b_r["tool_calls"])
    at = len(a_r["tool_calls"])
    dt = a_r["elapsed_sec"] - b_r["elapsed_sec"]
    mark = ""
    if not b_r["verdict"]["passed"] and a_r["verdict"]["passed"]:
        mark = " 🎉"
    elif b_r["verdict"]["passed"] and not a_r["verdict"]["passed"]:
        mark = " ⚠️回归"
    print(f"| {cid} | {a_r['category']} | {bm} | {am}{mark} | "
          f"{b_r['elapsed_sec']}s → {a_r['elapsed_sec']}s ({dt:+.1f}s) | {bt} → {at} ({at-bt:+d}) |")

print("\n## 工具调用变化\n")
print("| 工具 | 修复前 | 修复后 | 变化 |")
print("|------|--------|--------|------|")
for name in sorted(set(bc) | set(ac), key=lambda n: -(ac.get(n, 0) + bc.get(n, 0))):
    print(f"| `{name}` | {bc.get(name, 0)} | {ac.get(name, 0)} | "
          f"{ac.get(name, 0) - bc.get(name, 0):+d} |")
