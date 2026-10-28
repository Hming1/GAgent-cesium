"""Tests for result-layer promote + categorical attribute styling."""

import json
from pathlib import Path

from langchain_core.messages import ToolMessage

from models.geodata import DataType, GeoDataObject, LayerStyle
from services.tools import geostate_management, styling_tools
from services.tools.utils import collect_stylable_layers, promote_layers_to_map


def _layer(layer_id: str, name: str, data_link: str) -> GeoDataObject:
    return GeoDataObject(
        id=layer_id,
        data_source_id="test",
        data_type=DataType.GEOJSON,
        data_origin="tool",
        data_source="test",
        data_link=data_link,
        name=name,
        title=name,
        visible=True,
        style=LayerStyle(),
    )


def test_collect_stylable_layers_merges_results_when_map_has_layers():
    map_layer = _layer("map-1", "map", "http://example/map.geojson")
    result_layer = _layer("res-1", "schools", "http://example/schools.geojson")
    state = {
        "geodata_layers": [map_layer],
        "geodata_results": [result_layer],
        "geodata_last_results": [],
    }

    pool = collect_stylable_layers(state)
    ids = {layer.id for layer in pool}
    assert ids == {"map-1", "res-1"}

    matched = collect_stylable_layers(state, ["schools"])
    assert len(matched) == 1
    assert matched[0].id == "res-1"


def test_promote_layers_to_map_updates_results_collection():
    result_layer = _layer("res-1", "schools", "http://example/schools.geojson")
    styled = result_layer.model_copy(deep=True)
    styled.style = LayerStyle(fill_color="#ff0000")
    state = {
        "geodata_layers": [],
        "geodata_results": [result_layer],
        "geodata_last_results": [],
    }

    update = promote_layers_to_map(state, [styled])
    assert len(update["geodata_layers"]) == 1
    assert update["geodata_layers"][0].style.fill_color == "#ff0000"
    assert update["geodata_results"][0].style.fill_color == "#ff0000"


def test_style_map_layers_promotes_result_layer():
    result_layer = _layer("res-1", "schools", "http://example/schools.geojson")
    state = {
        "messages": [],
        "geodata_layers": [],
        "geodata_results": [result_layer],
        "geodata_last_results": [],
    }

    command = styling_tools.style_map_layers.func(
        state=state,
        tool_call_id="call-style-1",
        layer_names=["schools"],
        fill_color="#00aa00",
        stroke_color="#004400",
    )

    assert "geodata_layers" in command.update
    assert len(command.update["geodata_layers"]) == 1
    styled = command.update["geodata_layers"][0]
    assert styled.style.fill_color.lower() == "#00aa00"
    tool_message = command.update["messages"][-1]
    assert isinstance(tool_message, ToolMessage)
    assert "map" in tool_message.content.lower() or "地图" in tool_message.content


def test_add_layers_to_map_promotes_results_only():
    map_layer = _layer("map-1", "boundary", "http://example/boundary.geojson")
    result_layer = _layer("res-1", "schools", "http://example/schools.geojson")
    state = {
        "messages": [],
        "geodata_layers": [map_layer],
        "geodata_results": [result_layer],
        "geodata_last_results": [],
    }

    command = geostate_management.add_layers_to_map.func(
        state=state,
        tool_call_id="call-add-1",
        layer_names=None,
    )
    ids = {layer.id for layer in command.update["geodata_layers"]}
    assert ids == {"map-1", "res-1"}
    assert "Added 1 layer" in command.update["messages"][-1].content


def test_color_layers_by_attribute_writes_style_conditions():
    work = Path(__file__).resolve().parent / "_tmp_style_fixtures"
    work.mkdir(exist_ok=True)
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"adname": "天河区"},
                "geometry": {"type": "Point", "coordinates": [113.3, 23.1]},
            },
            {
                "type": "Feature",
                "properties": {"adname": "越秀区"},
                "geometry": {"type": "Point", "coordinates": [113.2, 23.1]},
            },
            {
                "type": "Feature",
                "properties": {"adname": "天河区"},
                "geometry": {"type": "Point", "coordinates": [113.31, 23.12]},
            },
        ],
    }
    path = work / "schools.geojson"
    path.write_text(json.dumps(geojson), encoding="utf-8")

    layer = _layer("res-1", "广州小学", str(path))
    state = {
        "messages": [],
        "geodata_layers": [],
        "geodata_results": [layer],
        "geodata_last_results": [],
    }

    command = styling_tools.color_layers_by_attribute.func(
        state=state,
        tool_call_id="call-color-1",
        field="adname",
        layer_names=["广州小学"],
        palette="Set2",
    )

    styled = command.update["geodata_layers"][0]
    conditions = styled.style.style_conditions
    assert "adname" in conditions
    color_map = conditions["adname"]["color_map"]
    assert set(color_map.keys()) == {"天河区", "越秀区"}
    assert all(str(v).startswith("#") for v in color_map.values())
    assert "adname" in command.update["messages"][-1].content


def test_color_layers_by_attribute_missing_field():
    work = Path(__file__).resolve().parent / "_tmp_style_fixtures"
    work.mkdir(exist_ok=True)
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "A"},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            }
        ],
    }
    path = work / "points.geojson"
    path.write_text(json.dumps(geojson), encoding="utf-8")
    layer = _layer("res-2", "points", str(path))
    state = {
        "messages": [],
        "geodata_layers": [layer],
        "geodata_results": [],
        "geodata_last_results": [],
    }

    command = styling_tools.color_layers_by_attribute.func(
        state=state,
        tool_call_id="call-color-2",
        field="adname",
    )
    assert "geodata_layers" not in command.update
    assert "not found" in command.update["messages"][-1].content.lower()
