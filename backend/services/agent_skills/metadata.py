"""Metadata and geostate management Skill."""

from services.agent_skills.base import AgentSkill, SelectorToolMetadata, ToolDisplayMetadata
from services.tools.geostate_management import (
    add_layers_to_map,
    list_user_layers,
    metadata_search,
)


METADATA_SKILL = AgentSkill(
    id="metadata",
    display_name="Metadata and State",
    description="查询当前会话中已有图层、近期结果和图层元数据。",
    tools={
        "search_metadata": metadata_search,
        "list_user_layers": list_user_layers,
        "add_layers_to_map": add_layers_to_map,
    },
    tool_metadata={
        "search_metadata": ToolDisplayMetadata(
            display_name="Metadata Search",
            category="metadata",
        ),
        "list_user_layers": ToolDisplayMetadata(
            display_name="List User Layers",
            category="metadata",
        ),
        "add_layers_to_map": ToolDisplayMetadata(
            display_name="Add Layers To Map",
            category="metadata",
        ),
    },
    selector_metadata={
        "search_metadata": SelectorToolMetadata(
            name="search_metadata",
            category="metadata",
            description=(
                "Search metadata for layers already loaded in the current map or recent "
                "results. Describe existing datasets, data sources, and layer details."
            ),
            always_include=True,
        ),
        "list_user_layers": SelectorToolMetadata(
            name="list_user_layers",
            category="metadata",
            description="List layers currently loaded on the map and generated result layers.",
            always_include=True,
        ),
        "add_layers_to_map": SelectorToolMetadata(
            name="add_layers_to_map",
            category="metadata",
            description=("Promote result layers onto the map so they become visible and stylable."),
            always_include=True,
        ),
        "metadata_search": SelectorToolMetadata(
            name="metadata_search",
            category="metadata",
            description=(
                "Search for existing geographic datasets, map layers, data sources, "
                "metadata, and current-session result details."
            ),
            always_include=True,
        ),
    },
    plan_aliases={
        "search_metadata": "search_metadata",
        "metadata_search": "search_metadata",
        "metadata": "search_metadata",
        "list_user_layers": "list_user_layers",
        "list_layers": "list_user_layers",
        "layers": "list_user_layers",
        "add_layers_to_map": "add_layers_to_map",
        "add_to_map": "add_layers_to_map",
        "promote_layers": "add_layers_to_map",
    },
    layer_keywords=(
        "图层",
        "加载",
        "数据",
        "检索",
        "上传",
        "文件",
        "显示",
        "地图",
        "上图",
        "加入地图",
        "layer",
        "data",
        "loaded",
        "geojson",
        "shp",
        "csv",
        "kml",
        "zip",
    ),
    prompt=(
        "- 回答任何图层或数据问题前，先查看 <system_state> 中的 geodata_layers、"
        "geodata_results 和 geodata_last_results。\n"
        "- 用户问当前加载了什么、有哪些图层、地图上有什么时，优先用 list_user_layers。\n"
        "- 用户问某个已有图层的来源、描述、字段线索或结果详情时，用 search_metadata。\n"
        "- 结果图层需要显示在地图上时，调用 add_layers_to_map，"
        "不要要求用户去结果列表手动勾选。\n"
        "- 不要为了回答已有图层的问题重新访问外部服务或数据库。"
    ),
)
