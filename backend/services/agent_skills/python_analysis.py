"""Python analysis sandbox Skill."""

from services.agent_skills.base import (
    AgentSkill,
    SelectorToolMetadata,
    ToolDisplayMetadata,
)
from services.tools.python_analysis_tool import run_python_analysis


PYTHON_ANALYSIS_SKILL = AgentSkill(
    id="python_analysis",
    display_name="Python Analysis Sandbox",
    description="在隔离沙箱中执行受限 Python/pandas/geopandas 自定义分析。",
    tools={"run_python_analysis": run_python_analysis},
    tool_metadata={
        "run_python_analysis": ToolDisplayMetadata(
            display_name="Python Analysis Sandbox",
            category="analysis",
            # Default on so area ranking / custom stats can fall back to sandbox
            # when dedicated geoprocess ops are insufficient. Requires
            # PYTHON_ANALYSIS_SANDBOX_URL; missing config returns a clear error.
            enabled=True,
        ),
    },
    selector_metadata={
        "run_python_analysis": SelectorToolMetadata(
            name="run_python_analysis",
            category="analysis",
            description=(
                "Run bounded Python, pandas, or geopandas analysis in an isolated sandbox "
                "against selected current map layers."
            ),
        ),
    },
    plan_aliases={
        "run_python_analysis": "run_python_analysis",
        "python_analysis": "run_python_analysis",
        "python": "run_python_analysis",
        "pandas": "run_python_analysis",
        "geopandas": "run_python_analysis",
    },
    layer_keywords=("python", "pandas", "geopandas", "自定义分析", "脚本"),
    prompt=(
        "- 优先用专用工具（attribute / geoprocess）。面积 TopN 先用 "
        "geoprocess area + attribute_tool2 sort_by；仅当专用工具失败再用沙箱。\n"
        "- 沙箱必须已注入 find_layer；若报 NameError: find_layer，停止重试沙箱，"
        "改走 geoprocess area，并提示重建 analysis-sandbox 镜像。\n"
        "- 沙箱 inputs 结构是 "
        "{{analysis_goal, layers: [{{name,title,geojson,...}}], params}}，"
        "不要写成 inputs[图层名]。优先用注入助手："
        "find_layer(name) / layer_to_gdf(layer) / load_gdfs([...])。\n"
        "- 面积请投影到米制 CRS（如 EPSG:32650）再 gdf.geometry.area；"
        "geojson_outputs 的 geojson 传 dict，不要 to_json() 字符串。"
        "若 layer['truncated'] 为 True，提高 max_features_per_layer 后重跑一次。\n"
        "- 不要把密钥、数据库 URL 写入沙箱代码。代码要短小确定；"
        "同一目标最多改一次代码重试，不要空转探查。"
    ),
)
