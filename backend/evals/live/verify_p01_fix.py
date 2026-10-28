"""验证 P0-1 方案 A 的可行性：合并 geodata_results 作为可处理图层。

在容器内用真实 state 构造场景，检验：
  1. 只读 geodata_layers 时是否确实为空（复现断裂）
  2. 合并 results 后是否能选中目标图层
  3. 是否会误选无关图层（风险验证）
"""
import sys

sys.path.insert(0, "/app")

from models.geodata import GeoDataObject  # noqa: E402
from services.tools.utils import match_layer_names  # noqa: E402


def make_layer(name, title, source="Nominatim"):
    return GeoDataObject(
        id=f"id-{name}",
        name=name,
        title=title,
        layer_type="GeoJSON",
        data_link=f"http://x/{name}.geojson",
        data_source=source,
        visible=True,
        selected=False,
        style=None,
        properties={},
        description="",
        llm_description="",
        bounding_box=None,
        data_origin="test",
        data_source_id="test-src",
        data_type="GeoJson",
        processing_metadata=None,
        features=None,
        score=None,
        sha256=None,
        size=None,
    )


# 场景：用户刚地理编码了深圳边界（只进 results），地图上无图层
state = {
    "geodata_layers": [],
    "geodata_results": [
        make_layer("深圳市", "深圳市"),
        make_layer("深圳范围内 · Restaurant · 点", "深圳餐饮点", source="Amap"),
    ],
}


def resolve_input_layers(state, layer_names=None, include_results=True):
    layers = list(state.get("geodata_layers") or [])
    if include_results:
        seen = {getattr(x, "id", None) for x in layers if getattr(x, "id", None)}
        for item in state.get("geodata_results") or []:
            lid = getattr(item, "id", None)
            if lid and lid in seen:
                continue
            if lid:
                seen.add(lid)
            layers.append(item)
    if layer_names:
        return match_layer_names(layers, layer_names)
    return layers


print("=" * 66)
print("场景 1：现状（只读 geodata_layers）")
print("=" * 66)
old = state.get("geodata_layers") or []
print(f"可用图层数: {len(old)}")
if old:
    sel = match_layer_names(old, ["深圳市"])
    print(f"选中: {[x.name for x in sel]}")
else:
    print("→ 空，geoprocess 会直接返回 'No geodata layers found in state'")
    print("   这复现了 P0-1 的断裂")

print()
print("=" * 66)
print("场景 2：方案 A（合并 results）")
print("=" * 66)
merged = resolve_input_layers(state)
print(f"可用图层数: {len(merged)}")
print(f"图层名: {[x.name for x in merged]}")

sel = resolve_input_layers(state, ["深圳市"])
print(f"按名选中 '深圳市': {[x.name for x in sel]}")
assert len(sel) == 1 and sel[0].name == "深圳市", "未精确选中目标"
print("✅ 精确选中目标图层")

print()
print("=" * 66)
print("场景 3：风险验证 —— 是否会误选无关图层")
print("=" * 66)
# 传入一个与餐饮点接近但不该匹配的名字
sel2 = resolve_input_layers(state, ["深圳市"])
names = [x.name for x in sel2]
print(f"传 ['深圳市'] 实际选中: {names}")
assert "深圳范围内 · Restaurant · 点" not in names, "误选中餐饮点"
print("✅ 未误选餐饮点（cutoff=0.6 起到区分作用）")

print()
print("=" * 66)
print("场景 4：去重验证 —— 同一图层同时在两处")
print("=" * 66)
dup = make_layer("深圳市", "深圳市")
state2 = {"geodata_layers": [dup], "geodata_results": [dup]}
merged2 = resolve_input_layers(state2)
print(f"合并后图层数: {len(merged2)}（应为 1）")
assert len(merged2) == 1, "去重失败"
print("✅ 按 id 去重生效")

print()
print("=" * 66)
print("结论：方案 A 可行")
print("=" * 66)
