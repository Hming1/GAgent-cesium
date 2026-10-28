"""Attribute and table operation Skill."""

from services.agent_skills.base import AgentSkill, SelectorToolMetadata, ToolDisplayMetadata
from services.tools.attribute_tool2 import attribute_tool2
from services.tools.attribute_tools import attribute_tool


ATTRIBUTES_SKILL = AgentSkill(
    id="attributes",
    display_name="Attribute Analysis",
    description="检查、筛选、汇总和重塑已有图层的属性表。",
    tools={
        "attribute_tool": attribute_tool,
        "attribute_tool2": attribute_tool2,
    },
    tool_metadata={
        "attribute_tool": ToolDisplayMetadata(
            display_name="Attribute Tool (Advanced)",
            category="attributes",
            group="attribute_tools",
            enabled=False,
        ),
        "attribute_tool2": ToolDisplayMetadata(
            display_name="Attribute Tool (Simplified)",
            category="attributes",
            group="attribute_tools",
        ),
    },
    selector_metadata={
        "attribute_tool": SelectorToolMetadata(
            name="attribute_tool",
            category="attributes",
            description=(
                "Work with feature attributes, fields, filters, SQL-like predicates, "
                "summaries, and property values of geographic layers."
            ),
        ),
        "attribute_tool2": SelectorToolMetadata(
            name="attribute_tool2",
            category="attributes",
            description=(
                "Advanced attribute operations: list fields, describe datasets, summarize "
                "columns, get unique values, filter, sort, and select fields."
            ),
        ),
    },
    plan_aliases={
        "attribute_tool": "attribute_tool",
        "attribute_tool2": "attribute_tool2",
        "attribute_tool_2": "attribute_tool2",
        "attributes": "attribute_tool2",
        "attribute": "attribute_tool2",
        "table": "attribute_tool2",
    },
    layer_keywords=(
        "属性",
        "字段",
        "筛选",
        "过滤",
        "统计",
        "汇总",
        "排序",
        "查询",
        "attribute",
        "field",
        "filter",
        "query",
        "summarize",
        "sort",
    ),
    prompt=(
        "- 用户询问字段、唯一值、属性筛选、排序、统计汇总或数据集描述时，"
        "优先使用 attribute_tool2。\n"
        "- 面对陌生数据集时，先 list_fields 或 describe_dataset，再执行筛选/汇总。\n"
        "- 字段名可能包含空格或特殊字符；过滤条件中需要时使用引号。\n"
        "- 多字段比较应尽量一次调用完成，不要对每个字段重复单独调用。\n"
        "- 结果要转成自然语言解释，说明单位、趋势和关键发现，不要只贴原始 JSON。"
    ),
)
