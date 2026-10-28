"""验证 match_layer_names 的误匹配风险（P0-1 方案 A 的关键风险点）。"""
import sys

sys.path.insert(0, "/app")

from models.geodata import GeoDataObject  # noqa: E402
from services.tools.utils import match_layer_names  # noqa: E402


def mk(name, title=None):
    return GeoDataObject(
        id=f"id-{name}", name=name, title=title or name, layer_type="GeoJSON",
        data_link=f"http://x/{name}.geojson", data_source="t", visible=True,
        selected=False, style=None, properties={}, description="",
        llm_description="", bounding_box=None, data_origin="t",
        data_source_id="s", data_type="GeoJson", processing_metadata=None,
        features=None, score=None, sha256=None, size=None,
    )


# 真实场景中同时候选的图层
pool = [
    mk("深圳市"),
    mk("广东省"),
    mk("深圳范围内 · Restaurant · 点"),
    mk("深圳市200米缓冲区"),
    mk("layer_park_areas_near_深圳"),
    mk("深圳市_school_面"),
]

cases = [
    ("深圳市", ["深圳市"]),
    ("深圳市", ["深圳"]),
    ("广东", ["广东省"]),
    ("深圳", ["深圳市"]),
    ("park", ["layer_park_areas_near_深圳"]),
    ("学校", ["深圳市_school_面"]),
    ("不存在的地方", ["某某不存在"]),
    ("深圳餐饮", ["深圳范围内 · Restaurant · 点"]),
]

print(f"{'target':22s} {'→ 实际匹配':40s} 结果")
print("-" * 90)
for target, names in cases:
    got = match_layer_names(pool, names)
    names_out = [x.name for x in got]
    ok = "✓" if names_out else "（无匹配）"
    exact = "精确" if names_out == names else ("⚠️ 含额外" if names_out else "空")
    print(f"{str(names):22s} → {str(names_out):40s} {ok} [{exact}]")
