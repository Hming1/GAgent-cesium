"""GeoServer and OGC service Skill."""

from services.agent_skills.base import AgentSkill, SelectorToolMetadata, ToolDisplayMetadata
from services.tools.geoserver.custom_geoserver import get_custom_geoserver_data


GEOSERVER_SKILL = AgentSkill(
    id="geoserver",
    display_name="GeoServer Data",
    description="从已配置 GeoServer/OGC 服务中发现和获取图层。",
    tools={"get_custom_geoserver_data": get_custom_geoserver_data},
    tool_metadata={
        "get_custom_geoserver_data": ToolDisplayMetadata(
            display_name="Custom GeoServer Data",
            category="data_retrieval",
        ),
    },
    selector_metadata={
        "get_custom_geoserver_data": SelectorToolMetadata(
            name="get_custom_geoserver_data",
            category="data_retrieval",
            description=(
                "Search configured GeoServer, WMS, WFS, WCS, and WMTS services for map "
                "layers. Use for OGC service backends and known GeoServer layers. "
                "Not for direct PostGIS table listing."
            ),
        ),
    },
    plan_aliases={
        "get_custom_geoserver_data": "get_custom_geoserver_data",
        "geoserver": "get_custom_geoserver_data",
        "ogc": "get_custom_geoserver_data",
        "wms": "get_custom_geoserver_data",
        "wfs": "get_custom_geoserver_data",
        "wcs": "get_custom_geoserver_data",
        "wmts": "get_custom_geoserver_data",
    },
    layer_keywords=("geoserver", "ogc", "wms", "wfs", "wcs", "wmts"),
    prompt=(
        "- get_custom_geoserver_data 只在用户明确提到 GeoServer、OGC、WMS、WFS、"
        "WCS、WMTS 或已知 GeoServer 图层时优先使用。\n"
        "- 如果用户只是说数据库、空间表、数据表，应优先进入 PostGIS Skill。\n"
        "- 用户已明确说「别管 GeoServer / 不要 WMS」时，本会话不要再调用本工具。\n"
        "- 查询 GeoServer 时优先使用过滤条件、bbox 或明确搜索词，避免无界请求。\n"
        "- 其他工具失败后，不要把 GeoServer 当作默认兜底数据源。"
    ),
)
