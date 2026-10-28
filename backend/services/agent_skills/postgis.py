"""PostGIS database Skill."""

from services.agent_skills.base import (
    AgentSkill,
    KeywordTrigger,
    SelectorToolMetadata,
    ToolDisplayMetadata,
)
from services.tools.postgis_tools import list_postgis_layers, load_postgis_layer


POSTGIS_TERMS = (
    "postgis",
    "postgres",
    "postgresql",
    "geometry_columns",
    "schema.table",
    "数据库",
    "資料庫",
    "资料库",
    "空间表",
    "空間表",
    "数据表",
    "資料表",
    "查询数据库",
    "查看数据库",
)

POSTGIS_LOAD_TERMS = (
    "load",
    "add",
    "加载",
    "載入",
    "加入",
    "添加",
    "导入",
    "載入地图",
)


POSTGIS_SKILL = AgentSkill(
    id="postgis",
    display_name="PostGIS Database",
    description="查看 PostGIS 中已有空间表，并按需加载为地图图层。",
    tools={
        "list_postgis_layers": list_postgis_layers,
        "load_postgis_layer": load_postgis_layer,
    },
    tool_metadata={
        "list_postgis_layers": ToolDisplayMetadata(
            display_name="List PostGIS Layers",
            category="data_retrieval",
            group="postgis",
        ),
        "load_postgis_layer": ToolDisplayMetadata(
            display_name="Load PostGIS Layer",
            category="data_retrieval",
            group="postgis",
        ),
    },
    selector_metadata={
        "list_postgis_layers": SelectorToolMetadata(
            name="list_postgis_layers",
            category="data_retrieval",
            description=(
                "List spatial tables available in the configured PostGIS database. "
                "Use for PostGIS, PostgreSQL spatial database, database tables, "
                "数据库, 空间表, 数据表, 查看数据库, 查询数据库."
            ),
        ),
        "load_postgis_layer": SelectorToolMetadata(
            name="load_postgis_layer",
            category="data_retrieval",
            description=(
                "Load a selected PostGIS spatial table into the map as a GeoDataObject. "
                "Use after listing tables or when the user names a schema.table."
            ),
        ),
    },
    plan_aliases={
        "list_postgis_layers": "list_postgis_layers",
        "load_postgis_layer": "load_postgis_layer",
        "postgis": "list_postgis_layers",
        "postgis_database": "list_postgis_layers",
        "postgis_layer": "load_postgis_layer",
        "database": "list_postgis_layers",
        "database_layers": "list_postgis_layers",
        "spatial_table": "list_postgis_layers",
    },
    layer_keywords=(
        "数据库",
        "空间表",
        "数据表",
        "查询数据库",
        "查看数据库",
        "postgis",
        "postgres",
        "postgresql",
        "table",
        "database",
    ),
    keyword_triggers=(
        KeywordTrigger(terms=POSTGIS_TERMS, tool_keys=("list_postgis_layers",)),
        KeywordTrigger(
            terms=POSTGIS_TERMS,
            require_any_terms=POSTGIS_LOAD_TERMS,
            tool_keys=("load_postgis_layer",),
        ),
    ),
    prompt=(
        "- 当用户提到数据库、PostGIS、空间表、数据表、查看数据库或查询数据库时，"
        "优先使用 PostGIS 工具，不要默认转向 GeoServer。\n"
        "- 工作流：先调用 list_postgis_layers 查看 schema、table、geometry_column，"
        "再对相关表调用 load_postgis_layer。\n"
        "- 不要编造表名或几何字段；必须使用 list_postgis_layers 返回的信息。\n"
        "- 加载时保持 row_limit 有界；加载后的 PostGIS 图层可继续用于属性分析和空间处理。\n"
        "- 只有用户明确说 GeoServer、WMS、WFS、WCS、WMTS 或 OGC 服务时，"
        "才优先选择 GeoServer。\n"
        "- list_postgis_layers 无匹配时：最多再试 1 次更宽/更准的关键词，或一次无 query 全量列表；"
        "禁止用 boundary/admin/city/area 等无关英文词连环试探。"
    ),
)
