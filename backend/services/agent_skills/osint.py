"""External open-source data Skill."""

from services.agent_skills.base import AgentSkill, SelectorToolMetadata, ToolDisplayMetadata
from services.tools.ecmwf_weather import get_ecmwf_weather_data
from services.tools.nasa_firms_fire import get_nasa_fire_data
from services.tools.nasa_gibs_imagery import get_nasa_gibs_layer, list_nasa_gibs_layers
from services.tools.world_bank_indicators import get_world_bank_data


OSINT_SKILL = AgentSkill(
    id="osint",
    display_name="External Data",
    description="获取世界银行、天气、火点和 NASA GIBS 影像等外部数据。",
    tools={
        "world_bank_indicators": get_world_bank_data,
        "ecmwf_weather": get_ecmwf_weather_data,
        "nasa_fire_data": get_nasa_fire_data,
        "nasa_gibs_layer": get_nasa_gibs_layer,
        "list_nasa_gibs_layers": list_nasa_gibs_layers,
    },
    tool_metadata={
        "world_bank_indicators": ToolDisplayMetadata(
            display_name="World Bank Economic Indicators",
            category="osint",
        ),
        "ecmwf_weather": ToolDisplayMetadata(
            display_name="ECMWF Weather Data",
            category="osint",
        ),
        "nasa_fire_data": ToolDisplayMetadata(
            display_name="NASA FIRMS Fire Detection Data",
            category="osint",
        ),
        "nasa_gibs_layer": ToolDisplayMetadata(
            display_name="NASA GIBS Satellite Imagery",
            category="osint",
        ),
        "list_nasa_gibs_layers": ToolDisplayMetadata(
            display_name="List NASA GIBS Layers",
            category="osint",
        ),
    },
    selector_metadata={
        "world_bank_indicators": SelectorToolMetadata(
            name="world_bank_indicators",
            category="osint",
            description="Retrieve World Bank economic and demographic indicators as layers.",
        ),
        "ecmwf_weather": SelectorToolMetadata(
            name="ecmwf_weather",
            category="osint",
            description=(
                "Retrieve historical or forecast weather data for a location " "or time range."
            ),
        ),
        "nasa_fire_data": SelectorToolMetadata(
            name="nasa_fire_data",
            category="osint",
            description="Retrieve NASA FIRMS active fire and hotspot detection data.",
        ),
        "nasa_gibs_layer": SelectorToolMetadata(
            name="nasa_gibs_layer",
            category="osint",
            description="Load NASA GIBS satellite imagery layers for map visualization.",
        ),
        "list_nasa_gibs_layers": SelectorToolMetadata(
            name="list_nasa_gibs_layers",
            category="osint",
            description="List available NASA GIBS satellite imagery layers.",
        ),
    },
    plan_aliases={
        "world_bank": "world_bank_indicators",
        "world_bank_indicators": "world_bank_indicators",
        "weather": "ecmwf_weather",
        "ecmwf": "ecmwf_weather",
        "ecmwf_weather": "ecmwf_weather",
        "fire": "nasa_fire_data",
        "nasa_fire": "nasa_fire_data",
        "nasa_fire_data": "nasa_fire_data",
        "nasa_gibs": "nasa_gibs_layer",
        "nasa_gibs_layer": "nasa_gibs_layer",
        "list_nasa_gibs_layers": "list_nasa_gibs_layers",
    },
    layer_keywords=("天气", "火点", "影像", "人口", "经济", "weather", "fire", "imagery"),
    prompt=(
        "- 外部数据工具只在用户明确请求对应主题时使用，例如世界银行指标、ECMWF 天气、"
        "NASA FIRMS 火点或 NASA GIBS 影像。\n"
        "- 查询前尽量确认地点、时间范围和指标名称；能用当前已有图层回答时优先用已有图层。"
    ),
)
