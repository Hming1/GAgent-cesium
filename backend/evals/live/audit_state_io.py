"""统计各工具对 geodata_layers / geodata_results 的读写行为，生成矩阵。"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TOOLS_DIR = Path(r"D:\code\Gagent-cesium\backend\services\tools")

WRITE_LAYERS = re.compile(r'["\']geodata_layers["\']\s*[:=]|update\[["\']geodata_layers["\']\]')
WRITE_RESULTS = re.compile(r'["\']geodata_results["\']\s*[:=]|update\[["\']geodata_results["\']\]')
READ_LAYERS = re.compile(r'state\.get\(\s*["\']geodata_layers["\']')
READ_RESULTS = re.compile(r'state\.get\(\s*["\']geodata_results["\']')

rows = []
for py in sorted(TOOLS_DIR.rglob("*.py")):
    if "__pycache__" in str(py):
        continue
    text = py.read_text(encoding="utf-8", errors="replace")
    wl = len(WRITE_LAYERS.findall(text))
    wr = len(WRITE_RESULTS.findall(text))
    rl = len(READ_LAYERS.findall(text))
    rr = len(READ_RESULTS.findall(text))
    if any([wl, wr, rl, rr]):
        rows.append((py.relative_to(TOOLS_DIR).as_posix(), wl, wr, rl, rr))

print(f"{'file':52s} {'W:layers':>9s} {'W:results':>10s} {'R:layers':>9s} {'R:results':>10s}")
print("-" * 96)
for name, wl, wr, rl, rr in rows:
    flag = ""
    # 只写 results、但读取 layers => 潜在断裂
    if wr and not wl and rl:
        flag = "  <== 只写 results 却读 layers"
    print(f"{name:52s} {wl:9d} {wr:10d} {rl:9d} {rr:10d}{flag}")
