"""Provider failover and GeoJSON behavior for geocoding."""

import json
from unittest.mock import Mock, patch

import pytest
import requests
from langgraph.types import Command

from services.tools.geocoding import geocode_using_nominatim_to_geostate


def response(payload=None, status_code=200):
    result = Mock()
    result.status_code = status_code
    result.json.return_value = payload
    return result


@pytest.fixture(autouse=True)
def clear_provider_keys(monkeypatch):
    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)
    monkeypatch.delenv("BAIDU_GEOCODING_AK", raising=False)


@pytest.mark.unit
def test_amap_used_after_nominatim_timeout(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    amap_payload = {
        "status": "1",
        "geocodes": [
            {
                "formatted_address": "Tiananmen, Beijing",
                "location": "116.403874,39.914889",
                "level": "POI",
            }
        ],
    }
    with (
        patch("requests.get") as mock_get,
        patch(
            "services.tools.geocoding.store_file", return_value=("stored://point", "point-id")
        ) as store,
    ):
        mock_get.side_effect = [requests.Timeout(), response(amap_payload)]
        state = {"messages": [], "geodata_results": []}
        result = geocode_using_nominatim_to_geostate.func(
            state=state, tool_call_id="call-1", query="\u5929\u5b89\u95e8"
        )

    assert isinstance(result, Command)
    assert len(result.update["geodata_results"]) == 1
    point = result.update["geodata_results"][0]
    assert point.data_source_id == "geocodeAmap"
    feature = json.loads(store.call_args.args[1])
    assert feature["geometry"]["type"] == "Point"
    lon, lat = feature["geometry"]["coordinates"]
    assert abs(lon - 116.3976) < 0.002
    assert abs(lat - 39.9135) < 0.002
    assert point.bounding_box is not None
    assert "Amap" in result.update["messages"][-1].content
    assert mock_get.call_args_list[1].kwargs["params"]["key"] == "test-amap-key"


@pytest.mark.unit
def test_baidu_used_when_amap_fails(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    monkeypatch.setenv("BAIDU_GEOCODING_AK", "test-baidu-key")
    with (
        patch("requests.get") as mock_get,
        patch(
            "services.tools.geocoding.store_file", return_value=("stored://point", "point-id")
        ) as store,
    ):
        mock_get.side_effect = [
            response([]),
            response({"status": "0", "info": "INVALID_USER_KEY"}),
            response(
                {
                    "status": 0,
                    "result": {
                        "location": {"lng": 116.403874, "lat": 39.914889},
                        "confidence": 90,
                    },
                }
            ),
        ]
        state = {"messages": [], "geodata_results": []}
        result = geocode_using_nominatim_to_geostate.func(
            state=state, tool_call_id="call-2", query="\u5929\u5b89\u95e8"
        )

    assert isinstance(result, Command)
    assert result.update["geodata_results"][0].data_source_id == "geocodeBaidu"
    assert "Baidu" in result.update["messages"][-1].content
    params = mock_get.call_args_list[2].kwargs["params"]
    assert params["ret_coordtype"] == "gcj02ll"
    assert params["ak"] == "test-baidu-key"
    feature = json.loads(store.call_args.args[1])
    assert feature["geometry"]["type"] == "Point"


@pytest.mark.unit
def test_nominatim_result_does_not_call_fallback(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    with patch("requests.get") as mock_get:
        mock_get.return_value = response(
            [{"name": "Paris", "display_name": "Paris, France", "lat": "48.85", "lon": "2.35"}]
        )
        result = geocode_using_nominatim_to_geostate.func(
            state={"messages": [], "geodata_results": []},
            tool_call_id="call-3",
            query="Paris",
            geojson=False,
        )

    assert result["results_summary"][0]["name"] == "Paris"
    assert mock_get.call_count == 1


@pytest.mark.unit
def test_all_providers_failing_returns_clear_message(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    monkeypatch.setenv("BAIDU_GEOCODING_AK", "test-baidu-key")
    with patch("requests.get") as mock_get:
        mock_get.side_effect = requests.Timeout()
        result = geocode_using_nominatim_to_geostate.func(
            state={"messages": [], "geodata_results": []},
            tool_call_id="call-4",
            query="\u5929\u5b89\u95e8",
        )

    assert result["message"] == "All configured geocoding providers failed."
    assert mock_get.call_count == 3


@pytest.mark.unit
def test_boundary_fallback_stores_polygon_not_point(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    with (
        patch("requests.get") as get,
        patch(
            "services.tools.geocoding.store_file", return_value=("stored://boundary", "id")
        ) as store,
    ):
        get.side_effect = [
            requests.Timeout(),
            response(
                {
                    "status": "1",
                    "districts": [
                        {
                            "name": "Hangzhou",
                            "adcode": "330100",
                            "level": "city",
                            "polyline": "120,30;120.1,30;120.1,30.1;120,30.1",
                        }
                    ],
                }
            ),
        ]
        result = geocode_using_nominatim_to_geostate.func(
            state={"messages": [], "geodata_results": []},
            tool_call_id="boundary",
            query="Hangzhou",
            require_boundary=True,
        )
    geometry = json.loads(store.call_args.args[1])["geometry"]
    assert geometry["type"] == "Polygon"
    assert geometry["coordinates"][0][0] == geometry["coordinates"][0][-1]
    assert abs(geometry["coordinates"][0][0][0] - 120) > 0.001
    assert result.update["geodata_results"][0].data_source_id == "geocodeAmap"
    assert get.call_args.kwargs["params"]["extensions"] == "all"
    assert get.call_args.kwargs["params"]["subdistrict"] == "0"


@pytest.mark.unit
def test_boundary_request_rejects_nominatim_point_and_never_calls_point_geocoders(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    monkeypatch.setenv("BAIDU_GEOCODING_AK", "test-baidu-key")
    with patch("requests.get") as get, patch("services.tools.geocoding.store_file") as store:
        get.side_effect = [
            response([{"geojson": {"type": "Point", "coordinates": [120, 30]}}]),
            response({"status": "1", "districts": [{"name": "Hangzhou", "polyline": ""}]}),
        ]
        result = geocode_using_nominatim_to_geostate.func(
            state={},
            tool_call_id="boundary",
            query="Hangzhou",
            require_boundary=True,
        )
    assert "boundary" in result["message"].lower()
    assert get.call_count == 2
    assert "/config/district" in get.call_args.args[0]
    store.assert_not_called()


@pytest.mark.unit
def test_overpass_location_uses_amap_when_nominatim_fails(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    from services.tools.geocoding import _geocode_location_for_overpass

    amap_payload = {
        "status": "1",
        "geocodes": [
            {
                "formatted_address": "People's Square, Shanghai",
                "location": "121.475000,31.230416",
            }
        ],
    }
    with patch("requests.get") as mock_get:
        mock_get.side_effect = [requests.Timeout(), response(amap_payload)]
        location, error = _geocode_location_for_overpass("\u4eba\u6c11\u5e7f\u573a")

    assert error is None
    assert location is not None
    assert location.lat is not None and location.lon is not None
    assert location.bbox is None
    assert location.osm_relation_id is None
    assert "Amap" in location.display_name
    assert "restapi.amap.com" in mock_get.call_args_list[1].args[0]


@pytest.mark.unit
def test_nominatim_boundary_retained_without_fallback(monkeypatch):
    from services.tools.geocoding import _geocode_with_fallback

    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    polygon = {"geojson": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]]}}
    with patch("requests.get", return_value=response([polygon])) as get:
        assert _geocode_with_fallback("city", True, 1, require_boundary=True) == [polygon]
    get.assert_called_once()


@pytest.mark.unit
@pytest.mark.parametrize(
    "polyline",
    [
        "",
        "120,30;121,30",
        "bad,data;121,30;121,31",
        "nan,30;121,30;121,31",
        "200,30;121,30;121,31",
        "120,30;121,31;120,31;121,30",
    ],
)
def test_invalid_boundary_not_used_for_clipping(monkeypatch, polyline):
    from services.tools.geocoding_fallback import geocode_boundary_with_amap

    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    with patch(
        "requests.get",
        return_value=response(
            {
                "status": "1",
                "districts": [{"name": "city", "polyline": polyline}],
            }
        ),
    ):
        assert geocode_boundary_with_amap("city", 1) == []


@pytest.mark.unit
def test_boundary_preserves_separate_parts(monkeypatch):
    from services.tools.geocoding_fallback import geocode_boundary_with_amap
    from shapely.geometry import shape

    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-amap-key")
    with patch(
        "requests.get",
        return_value=response(
            {
                "status": "1",
                "districts": [
                    {
                        "name": "city",
                        "polyline": "120,30;120.1,30;120,30.1|121,30;121.1,30;121,30.1",
                    }
                ],
            }
        ),
    ):
        result = geocode_boundary_with_amap("city", 1)[0]
    geometry = shape(result["geojson"])
    assert geometry.geom_type == "MultiPolygon"
    assert geometry.is_valid
    assert len(geometry.geoms) == 2
