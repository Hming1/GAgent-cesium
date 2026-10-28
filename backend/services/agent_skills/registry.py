"""Registry that composes concrete Skills into the legacy agent settings shape."""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Sequence, Set

from langchain_core.tools import BaseTool

from services.agent_skills.attributes import ATTRIBUTES_SKILL
from services.agent_skills.base import AgentSkill, SelectorToolMetadata
from services.agent_skills.geocoding import GEOCODING_SKILL
from services.agent_skills.geoprocessing import GEOPROCESSING_SKILL
from services.agent_skills.geoserver import GEOSERVER_SKILL
from services.agent_skills.inefficient_space import INEFFICIENT_SPACE_SKILL
from services.agent_skills.metadata import METADATA_SKILL
from services.agent_skills.osint import OSINT_SKILL
from services.agent_skills.planning import PLANNING_SKILL
from services.agent_skills.postgis import POSTGIS_SKILL
from services.agent_skills.python_analysis import PYTHON_ANALYSIS_SKILL
from services.agent_skills.styling import STYLING_SKILL


SKILLS: Sequence[AgentSkill] = (
    PLANNING_SKILL,
    METADATA_SKILL,
    GEOCODING_SKILL,
    POSTGIS_SKILL,
    GEOSERVER_SKILL,
    ATTRIBUTES_SKILL,
    GEOPROCESSING_SKILL,
    INEFFICIENT_SPACE_SKILL,
    STYLING_SKILL,
    OSINT_SKILL,
    PYTHON_ANALYSIS_SKILL,
)


BASE_SYSTEM_PROMPT = """
You are GeoAgent, an advanced geospatial assistant that helps users without GIS
expertise create maps and perform spatial analysis through natural language.
You MUST ALWAYS reply in Chinese.

# 交互与状态总规则
- 先读取本轮注入的 <system_state>，再决定是否需要调用工具。
- 如果用户需要的数据已经在 geodata_layers、geodata_results 或 geodata_last_results 中，
  必须优先复用当前数据，不要重复访问外部服务。
- 选择能完成目标的最简单工具；避免重复发现、重复加载和不必要的多工具链。
- 输入不明确时，只问一个会真正阻塞执行的澄清问题。
- 样式是 opt-in 行为，除非用户明确要求，不要自动改图层样式。
- 工具不可用或报错时，用中文简要说明原因，并给出下一步可行替代方案。
- 不要假设所有工具都启用；只使用当前运行时实际暴露的工具。
- 只回答本轮新问题；不要复述上一轮已经完整给出的结论或菜单。

# 工具失败收敛
- 单个工具失败时：简要说明原因，最多再尝试 1 次合理回退
  （例如外网地理编码失败后，改查本地 PostGIS 是否已有等价边界/表）。
- 禁止用多个无关联关键词反复调用同一发现类工具
  （例如连续 list_postgis_layers 试 boundary/admin/city/area/polygon）。
- 用户已明确排除的数据源（如「别管 GeoServer」）在本会话后续轮次不得再调用。
- 连续两次同类工具失败后必须停止继续调工具，向用户给出可选下一步，禁止空转。
- 回退失败后直接收敛，不要再切换到第三个无关数据源碰运气。

# 当前状态字段
- geodata_layers：用户当前选择并显示在地图上的图层。
- geodata_results：结果列表中的工具输出。
- geodata_last_results：最近一次工具输出，可直接复用。
- 识别图层时优先使用 title、name、description、llm_description、data_source、
  layer_type、bounding_box 等元数据。

# 结果图层可直接处理（重要）
- geodata_layers 为空 **不代表** 没有可用数据。只要 geodata_results 或
  geodata_last_results 中有图层，就视为可用输入。
- 用户用「刚才的」「上面那个」「这个图层」等指代上一轮产物时，直接从
  geodata_results / geodata_last_results 中取用，不要要求用户先去地图里勾选。
- 处理类工具（geoprocess、attribute、python 分析）已支持读取结果图层，
  因此可以直接调用；**不要**因为 geodata_layers 为空就放弃或反问。
- 样式类工具同样可读取结果图层，并会自动 promote 到 geodata_layers；
  也可先调用 add_layers_to_map。**禁止**要求用户手动勾选结果列表。
- 只有当结果集合也为空时，才向用户说明缺少数据并给出替代方案。

# 续跑与空承诺禁止
- 当你向用户给出可选下一步（例如「按区上色即可」），用户确认后，
  **本轮必须调用相应工具**，禁止只回复「好的，我先…」而不执行。
- 「按区 / 按字段 / 按类型上色」必须调用 color_layers_by_attribute；
  不要用 style_map_layers 假装完成层内分类上色。
- 不要承诺当前工具做不到的能力；能做的就立刻调工具。

# 查询类工具的终止规则
- list_user_layers / list_postgis_layers / metadata_search 返回空列表时，
  结论就是「确实没有」。**立即停止**，用一句话告知用户并给出下一步建议。
- 禁止对同一查询类工具重复调用以「确认」结果：一次空结果即为最终答案，
  重复调用不会改变结果，只会拖慢响应。
""".strip()


def _enabled_skills(skills: Sequence[AgentSkill] = SKILLS) -> Iterable[AgentSkill]:
    return (skill for skill in skills if skill.default_enabled)


def _ensure_unique_key(target: Mapping[str, object], key: str, skill_id: str) -> None:
    if key in target:
        raise ValueError(f"Duplicate tool key '{key}' while registering skill '{skill_id}'.")


def build_available_tools(skills: Sequence[AgentSkill] = SKILLS) -> Dict[str, BaseTool]:
    """Build the legacy DEFAULT_AVAILABLE_TOOLS mapping from Skill definitions."""
    tools: Dict[str, BaseTool] = {}
    for skill in _enabled_skills(skills):
        for key, tool in skill.tools.items():
            _ensure_unique_key(tools, key, skill.id)
            tools[key] = tool
    return tools


def build_tool_metadata(skills: Sequence[AgentSkill] = SKILLS) -> Dict[str, Dict[str, object]]:
    """Build UI/settings metadata for all registered Skill tools."""
    metadata: Dict[str, Dict[str, object]] = {}
    for skill in _enabled_skills(skills):
        for key, item in skill.tool_metadata.items():
            _ensure_unique_key(metadata, key, skill.id)
            metadata[key] = item.as_settings_metadata()
    return metadata


def build_selector_tool_metadata(
    skills: Sequence[AgentSkill] = SKILLS,
) -> Dict[str, SelectorToolMetadata]:
    """Build semantic selector metadata, including legacy tool-name aliases."""
    metadata: Dict[str, SelectorToolMetadata] = {}
    for skill in _enabled_skills(skills):
        for key, item in skill.selector_metadata.items():
            _ensure_unique_key(metadata, key, skill.id)
            metadata[key] = item
    return metadata


def build_system_prompt(skills: Sequence[AgentSkill] = SKILLS) -> str:
    """Compose the system prompt from ordered Skill prompt fragments."""
    sections: List[str] = [BASE_SYSTEM_PROMPT, "# Skill 调用规则"]
    for skill in _enabled_skills(skills):
        if skill.prompt:
            sections.append(f"## {skill.display_name}\n{skill.prompt.strip()}")
    return "\n\n".join(sections)


def build_plan_tool_aliases(skills: Sequence[AgentSkill] = SKILLS) -> Dict[str, str]:
    """Build normalized aliases used when executing a confirmed plan."""
    aliases: Dict[str, str] = {}
    for skill in _enabled_skills(skills):
        for alias, tool_key in skill.plan_aliases.items():
            aliases[alias] = tool_key
    return aliases


def build_layer_keywords(skills: Sequence[AgentSkill] = SKILLS) -> Set[str]:
    """Build query keywords that indicate layer/data state should be injected."""
    keywords: Set[str] = set()
    for skill in _enabled_skills(skills):
        keywords.update(skill.layer_keywords)
    return keywords


def required_tool_keys_for_query(
    query: str,
    available_tool_keys: Iterable[str],
    skills: Sequence[AgentSkill] = SKILLS,
) -> List[str]:
    """Return deterministic tools that explicit source keywords require."""
    available = set(available_tool_keys)
    required: List[str] = []

    for skill in _enabled_skills(skills):
        for trigger in skill.keyword_triggers:
            if trigger.matches(query):
                for tool_key in trigger.tool_keys:
                    if tool_key in available and tool_key not in required:
                        required.append(tool_key)

    return required
