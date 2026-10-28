"""resolve_input_layers must find named result layers even when the map is busy."""

from models.geodata import DataType, GeoDataObject, LayerStyle
from services.tools.utils import resolve_input_layers


def _layer(layer_id: str, name: str) -> GeoDataObject:
    return GeoDataObject(
        id=layer_id,
        data_source_id="test",
        data_type=DataType.GEOJSON,
        data_origin="tool",
        data_source="test",
        data_link=f"http://example/{name}.geojson",
        name=name,
        title=name,
        visible=True,
        style=LayerStyle(),
    )


def test_unnamed_lookup_keeps_map_only_when_map_nonempty():
    """Unnamed consumers still prefer the map and ignore results when map has data."""
    map_layer = _layer("map-1", "szu")
    result_layer = _layer("res-1", "parks")
    state = {
        "geodata_layers": [map_layer],
        "geodata_results": [result_layer],
        "geodata_last_results": [],
    }
    layers = resolve_input_layers(state)
    assert [layer.id for layer in layers] == ["map-1"]


def test_named_lookup_finds_result_layer_when_map_has_other_layers():
    """Regression: park describe after geocode while SZU is already on the map."""
    map_layer = _layer("map-1", "szu")
    result_layer = _layer("res-1", "parks-near-szu")
    state = {
        "geodata_layers": [map_layer],
        "geodata_results": [result_layer],
        "geodata_last_results": [],
    }
    matched = resolve_input_layers(state, ["parks-near-szu"])
    assert len(matched) == 1
    assert matched[0].id == "res-1"


def test_empty_map_still_falls_back_to_results():
    result_layer = _layer("res-1", "parks")
    state = {
        "geodata_layers": [],
        "geodata_results": [result_layer],
        "geodata_last_results": [],
    }
    layers = resolve_input_layers(state)
    assert [layer.id for layer in layers] == ["res-1"]


def test_overpass_guidance_tells_model_not_to_refetch():
    from services.tools.geocoding import _build_overpass_response_message

    msg = _build_overpass_response_message(
        amenity_display="park",
        search_mode="near 深圳大学",
        total_features=11,
        max_results=2500,
        layers_info=[{"name": "parks-near-szu", "title": "Parks"}],
        location_display="深圳大学",
    )
    assert "11" in msg
    assert "add_layers_to_map" in msg
    assert "set_result_list" not in msg
    assert "do NOT call geocode/overpass/attribute" in msg
