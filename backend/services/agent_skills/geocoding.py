"""Geocoding Skill."""

from services.agent_skills.base import AgentSkill, SelectorToolMetadata, ToolDisplayMetadata
from services.tools.geocoding import (
    geocode_using_nominatim_to_geostate,
    geocode_using_overpass_to_geostate,
)


GEOCODING_SKILL = AgentSkill(
    id="geocoding",
    display_name="Geocoding",
    description="将地点、行政区或 POI 查询转换为地图图层。",
    tools={
        "geocode_nominatim": geocode_using_nominatim_to_geostate,
        "geocode_overpass": geocode_using_overpass_to_geostate,
    },
    tool_metadata={
        "geocode_nominatim": ToolDisplayMetadata(
            display_name="Geocoding (Nominatim / Amap / Baidu)",
            category="geocoding",
        ),
        "geocode_overpass": ToolDisplayMetadata(
            display_name="POI Search (Amap first in China, else Overpass)",
            category="geocoding",
        ),
    },
    selector_metadata={
        "geocode_nominatim": SelectorToolMetadata(
            name="geocode_nominatim",
            category="geocoding",
            description=(
                "Find coordinates, boundaries, cities, countries, addresses, and "
                "administrative areas by place name."
            ),
        ),
        "geocode_overpass": SelectorToolMetadata(
            name="geocode_overpass",
            category="geocoding",
            description=(
                "Search POIs such as restaurants, parks, schools, and hospitals. "
                "In China, Amap Place Search is preferred; elsewhere Overpass/OSM is used."
            ),
        ),
        "geocode_using_nominatim_to_geostate": SelectorToolMetadata(
            name="geocode_using_nominatim_to_geostate",
            category="geocoding",
            description=(
                "Find geographic coordinates and locations by address or place name. "
                "Convert text locations to map geometry."
            ),
        ),
        "geocode_using_overpass_to_geostate": SelectorToolMetadata(
            name="geocode_using_overpass_to_geostate",
            category="geocoding",
            description=(
                "Search places, buildings, amenities, and POIs by name or type. "
                "Uses Amap first for China queries when configured."
            ),
        ),
    },
    plan_aliases={
        "geocode_nominatim": "geocode_nominatim",
        "geocode_using_nominatim_to_geostate": "geocode_nominatim",
        "nominatim": "geocode_nominatim",
        "geocode_overpass": "geocode_overpass",
        "geocode_using_overpass_to_geostate": "geocode_overpass",
        "overpass": "geocode_overpass",
        "poi_search": "geocode_overpass",
    },
    layer_keywords=(
        "边界",
        "地址",
        "地点",
        "位置",
        "poi",
        "place",
        "boundary",
        "address",
        "location",
    ),
    prompt=(
        "- 先检查当前状态中是否已有可用图层；已有等价数据时不要重新地理编码。\n"
        "- geocode_nominatim 适合地点、地址、城市、国家、行政区边界。\n"
        "- 行政边界、裁剪范围或面积分析必须设置 require_boundary=True；query 只传行政区名或 adcode，单个城市用 maxRows=1。\n"
        "- 工具自动从 Nominatim 切换到高德行政区域查询获取边界面；普通地址点查询依次尝试高德和百度。不要把城市中心点作为边界。\n"
        "- geocode_overpass 适合在指定范围内查找 POI 或地物类型，例如公园、医院、学校、中学。\n"
        "- 国内 POI（中文地名/中国境内）优先走高德地点搜索；高德无结果或未配置 Key 时再回退 Overpass/OSM。\n"
        "- 查中学请用 amenity_key=school 且 query 含「中学」，高德会映射到中学类型；不要先拉全部学校再枚举校名。\n"
        "- Overpass 路径需要先定位中心或范围：Nominatim 失败时必须改用高德、再百度拿到坐标，"
        "不要在未尝试这两家之前就放弃或改搜别的数据源。\n"
        "- 查询范围要尽量明确；范围过大或名称有歧义时，先问一个简短澄清问题。\n"
        "- 地理编码网络失败时：最多 1 次回退到本地 PostGIS 按地名检索；"
        "仍无结果则停止工具调用，请用户上传边界或给出表名，不要关键词轰炸或改去 GeoServer。"
    ),
)
