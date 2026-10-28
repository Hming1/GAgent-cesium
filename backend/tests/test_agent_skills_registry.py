from types import SimpleNamespace

from services import single_agent
from services.agent_skills import (
    build_available_tools,
    build_plan_tool_aliases,
    build_selector_tool_metadata,
    build_system_prompt,
    build_tool_metadata,
    required_tool_keys_for_query,
)
from services.default_agent_settings import (
    DEFAULT_AVAILABLE_TOOLS,
    DEFAULT_SYSTEM_PROMPT,
    TOOL_METADATA,
)
from services.tool_selector import TOOL_METADATA as SELECTOR_TOOL_METADATA


def test_skill_registry_exports_legacy_default_settings():
    assert set(DEFAULT_AVAILABLE_TOOLS) == set(build_available_tools())
    assert TOOL_METADATA == build_tool_metadata()
    assert DEFAULT_SYSTEM_PROMPT == build_system_prompt()

    assert "list_postgis_layers" in DEFAULT_AVAILABLE_TOOLS
    assert "load_postgis_layer" in DEFAULT_AVAILABLE_TOOLS
    assert "get_custom_geoserver_data" in DEFAULT_AVAILABLE_TOOLS
    assert TOOL_METADATA["run_python_analysis"]["enabled"] is True


def test_skill_prompt_contains_source_routing_rules():
    prompt = build_system_prompt()

    assert "Skill 调用规则" in prompt
    assert "list_postgis_layers" in prompt
    assert "load_postgis_layer" in prompt
    assert "GeoServer" in prompt
    assert "数据库" in prompt
    assert "You MUST ALWAYS reply in Chinese" in prompt
    assert "工具失败收敛" in prompt
    assert "最多再尝试 1 次合理回退" in prompt
    assert "别管 GeoServer" in prompt


def test_postgis_keyword_triggers_are_registry_driven():
    available = {
        "list_postgis_layers",
        "load_postgis_layer",
        "get_custom_geoserver_data",
    }

    assert required_tool_keys_for_query("查看数据库里有哪些空间表", available) == [
        "list_postgis_layers"
    ]
    assert required_tool_keys_for_query("加载 PostGIS 的 public.parks", available) == [
        "list_postgis_layers",
        "load_postgis_layer",
    ]
    assert required_tool_keys_for_query("查询 GeoServer 的 WMS 图层", available) == []


def test_selector_metadata_is_built_from_skill_registry():
    registry_metadata = build_selector_tool_metadata()

    assert SELECTOR_TOOL_METADATA == registry_metadata
    assert SELECTOR_TOOL_METADATA["list_postgis_layers"].category == "data_retrieval"
    assert SELECTOR_TOOL_METADATA["metadata_search"].always_include is True
    assert "geocode_using_nominatim_to_geostate" in SELECTOR_TOOL_METADATA
    assert "geoprocess_tool" in SELECTOR_TOOL_METADATA


def test_plan_tool_aliases_are_built_from_skill_registry():
    aliases = build_plan_tool_aliases()

    assert aliases["database"] == "list_postgis_layers"
    assert aliases["postgis_layer"] == "load_postgis_layer"
    assert aliases["geoprocess_tool"] == "geoprocess"

    tools = {
        "list_postgis_layers": SimpleNamespace(name="list_postgis_layers"),
        "load_postgis_layer": SimpleNamespace(name="load_postgis_layer"),
        "get_custom_geoserver_data": SimpleNamespace(name="get_custom_geoserver_data"),
    }

    filtered = single_agent._filter_tools_for_confirmed_plan(tools, ["database"])
    assert set(filtered) == {"list_postgis_layers"}

    filtered = single_agent._filter_tools_for_confirmed_plan(tools, ["postgis layer"])
    assert set(filtered) == {"load_postgis_layer"}
