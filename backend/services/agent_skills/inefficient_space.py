"""Urban inefficient-space identification Skill."""

from services.agent_skills.base import (
    AgentSkill,
    KeywordTrigger,
    SelectorToolMetadata,
    ToolDisplayMetadata,
)
from services.tools.inefficient_space_tools import (
    analyze_inefficient_space_tool,
    get_inefficient_presets,
    infer_inefficient_field_mapping,
)


INEFFICIENT_TERMS = (
    "低效",
    "低效空间",
    "低效用地",
    "闲置空地",
    "闲置用地",
    "容积率判别",
    "建筑密度判别",
    "工业低效",
    "商业低效",
    "居住低效",
    "inefficient",
    "idle vacant",
    "vacant land",
)


INEFFICIENT_SPACE_SKILL = AgentSkill(
    id="inefficient_space",
    display_name="Inefficient Space",
    description="城市低效空间判别：识别闲置空地与工业/商业/居住低效用地并上图。",
    tools={
        "get_inefficient_presets": get_inefficient_presets,
        "infer_inefficient_field_mapping": infer_inefficient_field_mapping,
        "analyze_inefficient_space": analyze_inefficient_space_tool,
    },
    tool_metadata={
        "get_inefficient_presets": ToolDisplayMetadata(
            display_name="Inefficient Space Presets",
            category="analysis",
            group="inefficient_space",
        ),
        "infer_inefficient_field_mapping": ToolDisplayMetadata(
            display_name="Infer Inefficient Field Mapping",
            category="analysis",
            group="inefficient_space",
        ),
        "analyze_inefficient_space": ToolDisplayMetadata(
            display_name="Analyze Inefficient Space",
            category="analysis",
            group="inefficient_space",
        ),
    },
    selector_metadata={
        "get_inefficient_presets": SelectorToolMetadata(
            name="get_inefficient_presets",
            category="analysis",
            description=(
                "Get default thresholds and field aliases for urban inefficient-space "
                "identification (FAR, building density, idle years, tax, land use)."
            ),
        ),
        "infer_inefficient_field_mapping": SelectorToolMetadata(
            name="infer_inefficient_field_mapping",
            category="analysis",
            description=(
                "Infer parcel attribute mapping for inefficient-space indicators and "
                "ask one clarifying question when critical fields are missing."
            ),
        ),
        "analyze_inefficient_space": SelectorToolMetadata(
            name="analyze_inefficient_space",
            category="analysis",
            description=(
                "Classify urban inefficient space: idle vacant, industrial, commercial, "
                "residential inefficient parcels. Use for 低效空间, 闲置空地, 容积率判别."
            ),
            usage_weight=1.2,
        ),
        # Legacy/plan alias keys used by the selector.
        "analyze_inefficient_space_tool": SelectorToolMetadata(
            name="analyze_inefficient_space_tool",
            category="analysis",
            description=("Classify urban inefficient parcels using rule-based indicators."),
        ),
    },
    plan_aliases={
        "analyze_inefficient_space": "analyze_inefficient_space",
        "analyze_inefficient_space_tool": "analyze_inefficient_space",
        "infer_inefficient_field_mapping": "infer_inefficient_field_mapping",
        "get_inefficient_presets": "get_inefficient_presets",
        "inefficient_space": "analyze_inefficient_space",
        "low_efficiency": "analyze_inefficient_space",
        "idle_vacant": "analyze_inefficient_space",
        "低效空间": "analyze_inefficient_space",
        "闲置空地": "analyze_inefficient_space",
        "容积率判别": "analyze_inefficient_space",
    },
    layer_keywords=(
        "低效",
        "闲置",
        "空地",
        "容积率",
        "建筑密度",
        "税收",
        "用地性质",
        "工业低效",
        "商业低效",
        "居住低效",
        "inefficient",
        "vacant",
    ),
    keyword_triggers=(
        KeywordTrigger(
            terms=INEFFICIENT_TERMS,
            tool_keys=(
                "get_inefficient_presets",
                "infer_inefficient_field_mapping",
                "analyze_inefficient_space",
            ),
        ),
    ),
    prompt=(
        "- 用户提到低效空间、低效用地、闲置空地、容积率判别、工业/商业/居住低效时，"
        "优先使用本 Skill 工具，而不是只用通用属性筛选或 Python 沙箱。\n"
        "- 推荐工作流：\n"
        "  1) 若地块不在当前图层，先 list_postgis_layers / load_postgis_layer 或请用户上传；\n"
        "  2) 调用 infer_inefficient_field_mapping 推断字段；\n"
        "  3) 若返回 clarifying_question，只问这一个问题，等用户答复后再继续；\n"
        "  4) 需要解释默认阈值时调用 get_inefficient_presets；\n"
        "  5) 调用 analyze_inefficient_space 生成结果图层并中文汇总命中数量与面积。\n"
        "- 计划模式：复杂请求先 create_execution_plan，步骤应包含"
        "数据加载 → 字段映射 → 判别分析 → 结果说明。\n"
        "- 用户给出城市定制阈值时，在最终回复中明确复述这些阈值；"
        "若工具返回 memory_suggestion，可提示用户将其记为该城市默认规则。\n"
        "- 不要编造字段名；映射必须来自 infer 结果或用户确认。"
    ),
)
