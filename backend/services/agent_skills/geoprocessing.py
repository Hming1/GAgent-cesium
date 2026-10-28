"""Geoprocessing Skill."""

from services.agent_skills.base import (
    AgentSkill,
    SelectorToolMetadata,
    ToolDisplayMetadata,
)
from services.tools.geoprocess_tools import geoprocess_tool


GEOPROCESSING_SKILL = AgentSkill(
    id="geoprocessing",
    display_name="Geoprocessing",
    description="对已有矢量图层执行缓冲、叠加、裁剪、合并等空间分析。",
    tools={"geoprocess": geoprocess_tool},
    tool_metadata={
        "geoprocess": ToolDisplayMetadata(
            display_name="Geoprocessing Operations",
            category="geoprocessing",
        ),
    },
    selector_metadata={
        "geoprocess": SelectorToolMetadata(
            name="geoprocess",
            category="geoprocessing",
            description=(
                "Perform spatial analysis operations: buffer, clip, intersect, union, "
                "dissolve, centroid, area, distance, overlay, and merge."
            ),
        ),
        "geoprocess_tool": SelectorToolMetadata(
            name="geoprocess_tool",
            category="geoprocessing",
            description=(
                "Perform spatial analysis operations including buffer, clip, intersect, "
                "union, difference, distance, area, and overlay."
            ),
        ),
    },
    plan_aliases={
        "geoprocess": "geoprocess",
        "geoprocess_tool": "geoprocess",
        "geoprocessing": "geoprocess",
        "buffer": "geoprocess",
        "intersect": "geoprocess",
        "clip": "geoprocess",
    },
    layer_keywords=(
        "分析",
        "空间",
        "缓冲",
        "相交",
        "裁剪",
        "合并",
        "面积",
        "长度",
        "距离",
        "计算",
        "处理",
        "spatial",
        "buffer",
        "intersect",
        "clip",
        "merge",
        "area",
        "distance",
    ),
    prompt=(
        "- 用户要求缓冲、相交、裁剪、合并、面积、距离、叠加等空间分析时，"
        "使用 geoprocess 工具。\n"
        "- 需要面积 TopN：先 geoprocess operation 含 area（米制 CRS），"
        "再 attribute_tool2 sort_by area 字段；不要优先烧沙箱配额。\n"
        "- clip 时 target_layer_names 顺序为 [被裁剪图层, 裁剪范围图层]。\n"
        "- 先确认输入图层已存在且空间范围有交集；缺少 AOI 或图层时只问一个必要问题。\n"
        "- 属性条件驱动的任务先用 attribute_tool2 过滤，再做空间处理。\n"
        "- 输出命名要清楚，避免覆盖用户已有图层。"
    ),
)
