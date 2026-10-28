"""Tests for inefficient-space agent tools and skill registration."""

from __future__ import annotations

import json
from types import SimpleNamespace

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from shapely.geometry import box

from services.agent_skills import (
    build_available_tools,
    build_plan_tool_aliases,
    build_system_prompt,
    required_tool_keys_for_query,
)
from services.inefficient_space.field_mapping import infer_mapping_from_columns
from services.tools import inefficient_space_tools


def base_state(layers=None):
    return {
        "messages": [HumanMessage(content="识别低效空间")],
        "geodata_layers": layers or [],
        "geodata_results": [],
        "geodata_last_results": [],
        "results_title": "",
        "options": {},
        "execution_plan": None,
        "remaining_steps": 10,
    }


def test_infer_mapping_from_columns_matches_aliases():
    result = infer_mapping_from_columns(["容积率", "建筑密度", "用地性质", "税收", "闲置年限"])
    assert result["matched"]["far"] == "容积率"
    assert result["matched"]["land_use"] == "用地性质"
    assert result["clarifying_question"] is None


def test_infer_mapping_asks_one_question_when_critical_missing():
    result = infer_mapping_from_columns(["name", "area"])
    assert "land_use" in result["critical_missing"]
    assert result["clarifying_question"]
    assert "用地性质" in result["clarifying_question"]


def test_skill_registry_includes_inefficient_space_tools():
    tools = build_available_tools()
    assert "analyze_inefficient_space" in tools
    assert "infer_inefficient_field_mapping" in tools
    assert "get_inefficient_presets" in tools

    prompt = build_system_prompt()
    assert "低效空间" in prompt
    assert "infer_inefficient_field_mapping" in prompt

    aliases = build_plan_tool_aliases()
    assert aliases["闲置空地"] == "analyze_inefficient_space"
    assert aliases["容积率判别"] == "analyze_inefficient_space"


def test_inefficient_keyword_triggers():
    available = {
        "get_inefficient_presets",
        "infer_inefficient_field_mapping",
        "analyze_inefficient_space",
        "list_postgis_layers",
    }
    keys = required_tool_keys_for_query("请识别工业低效用地和闲置空地", available)
    assert "analyze_inefficient_space" in keys
    assert "infer_inefficient_field_mapping" in keys


def test_get_inefficient_presets_tool():
    cmd = inefficient_space_tools.get_inefficient_presets.func(
        state=base_state(), tool_call_id="p1"
    )
    assert isinstance(cmd, Command)
    payload = json.loads(cmd.update["messages"][0].content)
    assert "thresholds" in payload
    assert "field_mapping" in payload


def test_infer_field_mapping_tool(monkeypatch):
    import geopandas as gpd

    layer = SimpleNamespace(
        id="parcel-1",
        name="parcels",
        title="parcels",
        data_link="http://example/parcels.geojson",
        data_type="GeoJson",
    )
    gdf = gpd.GeoDataFrame(
        {
            "容积率": [0.5],
            "建筑密度": [0.2],
            "用地性质": ["工业"],
            "geometry": [box(0, 0, 1, 1)],
        },
        crs=4326,
    )
    monkeypatch.setattr(inefficient_space_tools, "_load_gdf", lambda link: gdf)

    cmd = inefficient_space_tools.infer_inefficient_field_mapping.func(
        state=base_state([layer]),
        tool_call_id="m1",
        parcel_layer_name="parcels",
    )
    assert isinstance(cmd, Command)
    payload = json.loads(cmd.update["messages"][0].content)
    assert payload["matched"]["far"] == "容积率"
    assert payload["clarifying_question"] is None


def test_analyze_inefficient_space_tool(monkeypatch):
    layer = SimpleNamespace(
        id="parcel-1",
        name="parcels",
        title="parcels",
        data_link="http://example/parcels.geojson",
        data_type="GeoJson",
    )

    fake_layer = SimpleNamespace(
        id="result-1",
        name="低效空间判别结果",
        data_link="http://example/result.geojson",
    )
    fake_summary = SimpleNamespace(
        model_dump=lambda: {
            "total": 3,
            "matched": 2,
            "by_type": {"industrial": {"count": 2, "area_sqm": 1000}},
            "area_stats": {},
        }
    )
    fake_response = SimpleNamespace(layer=fake_layer, summary=fake_summary)

    monkeypatch.setattr(
        inefficient_space_tools,
        "analyze_inefficient_space",
        lambda request: fake_response,
    )

    cmd = inefficient_space_tools.analyze_inefficient_space_tool.func(
        state=base_state([layer]),
        tool_call_id="a1",
        parcel_layer_name="parcels",
        city_name="示例市",
    )
    assert isinstance(cmd, Command)
    assert cmd.update["geodata_last_results"][0].id == "result-1"
    assert any(getattr(item, "id", None) == "result-1" for item in cmd.update["geodata_layers"])
    payload = json.loads(cmd.update["messages"][0].content)
    assert payload["summary"]["matched"] == 2
    assert payload["memory_suggestion"]
    assert "示例市" in payload["memory_suggestion"]
