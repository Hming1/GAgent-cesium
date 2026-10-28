"""Planning Skill."""

from services.agent_skills.base import AgentSkill, SelectorToolMetadata, ToolDisplayMetadata
from services.tools.geostate_management import create_execution_plan


PLANNING_SKILL = AgentSkill(
    id="planning",
    display_name="Execution Planning",
    description="为复杂 GIS 任务生成执行计划，并在用户确认后再执行。",
    tools={"create_execution_plan": create_execution_plan},
    tool_metadata={
        "create_execution_plan": ToolDisplayMetadata(
            display_name="Create Execution Plan",
            category="planning",
        ),
    },
    selector_metadata={
        "create_execution_plan": SelectorToolMetadata(
            name="create_execution_plan",
            category="planning",
            description="Create a structured execution plan for complex multi-step GIS tasks.",
        ),
    },
    plan_aliases={
        "create_execution_plan": "create_execution_plan",
        "execution_plan": "create_execution_plan",
        "plan": "create_execution_plan",
    },
    prompt=(
        "- 当开启计划模式时，新用户请求必须先调用 create_execution_plan 生成步骤，"
        "然后等待用户确认。\n"
        "- 用户确认后，直接执行计划中列出的业务工具，不要再次创建计划。\n"
        "- 计划应写清楚目标、输入图层、预期工具和输出结果。"
    ),
)
