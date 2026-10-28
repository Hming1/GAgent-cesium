"""Amap-first domestic POI search and Overpass fallback."""

from unittest.mock import Mock, patch

import pytest
from langgraph.types import Command

from services.tools.geocoding import geocode_using_overpass_to_geostate
from services.tools.geocoding_fallback import (
    AMAP_DISTRICT_URL,
    _amap_city_district_adcodes,
    _get_amap_json,
    gcj02_to_wgs84,
    haversine_meters,
    looks_like_china_query,
    resolve_amap_poi_types,
    search_amap_pois,
    wgs84_to_gcj02,
)
from services.tools.overpass import OverpassLocation


@pytest.fixture(autouse=True)
def clear_amap_key(monkeypatch):
    monkeypatch.delenv("AMAP_WEB_SERVICE_KEY", raising=False)


def test_resolve_amap_types_for_middle_school():
    assert resolve_amap_poi_types("school", "深圳的中学") == "141202"
    assert resolve_amap_poi_types("school", "schools") == "141200"
    assert resolve_amap_poi_types("hospital", "") == "090100|090200"


def test_looks_like_china_query():
    assert looks_like_china_query("深圳")
    assert looks_like_china_query("Shenzhen", display_name="深圳市, 广东省, 中国")
    assert looks_like_china_query("area", lat=22.5, lon=114.0)
    assert not looks_like_china_query("Paris", lat=48.8, lon=2.3)


def test_search_amap_pois_paginates_and_converts_to_wgs84(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    page1 = {
        "status": "1",
        "pois": [
            {
                "id": "1",
                "name": "翠园中学",
                "location": "114.123456,22.555555",
                "type": "中学",
                "typecode": "141202",
                "address": "罗湖区",
                "cityname": "深圳市",
            }
        ],
    }
    page2 = {"status": "1", "pois": []}
    no_district = {"status": "1", "districts": []}
    with patch("services.tools.geocoding_fallback._get_json") as mock_get:
        mock_get.side_effect = [no_district, page1, page2]
        features = search_amap_pois(
            amenity_key="school",
            query="深圳的中学",
            location_name="深圳",
            max_results=50,
        )

    assert len(features) == 1
    assert features[0]["properties"]["name"] == "翠园中学"
    lon, lat = features[0]["geometry"]["coordinates"]
    # Must convert GCJ-02 → WGS84 (≈ hundreds of metres), not leave raw Amap coords.
    assert haversine_meters(114.123456, 22.555555, lon, lat) > 100
    expected = gcj02_to_wgs84(114.123456, 22.555555)
    assert abs(lon - expected[0]) < 1e-8
    assert abs(lat - expected[1]) < 1e-8
    assert features[0]["properties"]["crs"] == "EPSG:4326"
    assert features[0]["properties"]["coord_transform"] == "gcj02_to_wgs84"
    assert features[0]["properties"]["gcj02"] == [114.123456, 22.555555]
    params = mock_get.call_args_list[1].args[1]
    assert params["types"] == "141202"
    assert params["city"] == "深圳"
    assert params["keywords"] == "中学"


def test_gcj02_wgs84_roundtrip_stays_under_one_metre():
    samples = [
        (116.397428, 39.90923),
        (114.057868, 22.543099),
        (121.473701, 31.230416),
    ]
    for glon, glat in samples:
        wlon, wlat = gcj02_to_wgs84(glon, glat)
        back = wgs84_to_gcj02(wlon, wlat)
        assert haversine_meters(glon, glat, *back) < 1.0
        assert haversine_meters(glon, glat, wlon, wlat) > 100


def _poi(poi_id, name, adname):
    return {
        "id": poi_id,
        "name": name,
        "location": "114.05,22.55",
        "typecode": "141202",
        "adname": adname,
    }


def _route_amap(district_payload, pois_by_city):
    """Fake _get_json: district lookup, then one POI page per city/adcode."""

    def fake(url, params):
        if url == AMAP_DISTRICT_URL:
            return district_payload
        if params.get("page") != "1":
            return {"status": "1", "pois": []}
        return {"status": "1", "pois": pois_by_city.get(params.get("city"), [])}

    return fake


def test_city_level_search_is_split_by_district_and_merged(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    district_payload = {
        "status": "1",
        "districts": [
            {
                "name": "深圳市",
                "level": "city",
                "adcode": "440300",
                "districts": [
                    {"name": "罗湖区", "level": "district", "adcode": "440303"},
                    {"name": "南山区", "level": "district", "adcode": "440305"},
                ],
            }
        ],
    }
    pois = {
        "440303": [_poi("a", "翠园中学", "罗湖区"), _poi("dup", "边界中学", "罗湖区")],
        "440305": [_poi("b", "南山中学", "南山区"), _poi("dup", "边界中学", "南山区")],
    }
    with patch(
        "services.tools.geocoding_fallback._get_json",
        side_effect=_route_amap(district_payload, pois),
    ) as mock_get:
        features = search_amap_pois(
            amenity_key="school", query="深圳的中学", location_name="深圳市"
        )

    assert sorted(f["properties"]["name"] for f in features) == ["南山中学", "翠园中学", "边界中学"]
    queried = [
        c.args[1].get("city") for c in mock_get.call_args_list if c.args[0] != AMAP_DISTRICT_URL
    ]
    assert set(queried) == {"440303", "440305"}


def test_district_level_search_queries_directly(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    district_payload = {
        "status": "1",
        "districts": [
            {
                "name": "南山区",
                "level": "district",
                "adcode": "440305",
                "districts": [{"name": "粤海街道", "level": "street", "adcode": "440305"}],
            }
        ],
    }
    pois = {"南山区": [_poi("b", "南山中学", "南山区")]}
    with patch(
        "services.tools.geocoding_fallback._get_json",
        side_effect=_route_amap(district_payload, pois),
    ) as mock_get:
        features = search_amap_pois(
            amenity_key="school", query="南山区的中学", location_name="南山区"
        )

    assert [f["properties"]["name"] for f in features] == ["南山中学"]
    queried = [
        c.args[1].get("city") for c in mock_get.call_args_list if c.args[0] != AMAP_DISTRICT_URL
    ]
    assert set(queried) == {"南山区"}


def test_municipality_is_split_through_nested_city_node(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    district_payload = {
        "status": "1",
        "districts": [
            {
                "name": "北京市",
                "level": "province",
                "adcode": "110000",
                "districts": [
                    {
                        "name": "北京城区",
                        "level": "city",
                        "adcode": "110100",
                        "districts": [
                            {"name": "东城区", "level": "district", "adcode": "110101"},
                            {"name": "西城区", "level": "district", "adcode": "110102"},
                        ],
                    }
                ],
            }
        ],
    }
    with patch(
        "services.tools.geocoding_fallback._get_json",
        side_effect=_route_amap(district_payload, {}),
    ):
        assert _amap_city_district_adcodes("test-key", "北京市") == ["110101", "110102"]


def test_ordinary_province_is_not_split(monkeypatch):
    district_payload = {
        "status": "1",
        "districts": [
            {
                "name": "广东省",
                "level": "province",
                "districts": [
                    {"name": "深圳市", "level": "city", "adcode": "440300"},
                    {"name": "广州市", "level": "city", "adcode": "440100"},
                ],
            }
        ],
    }
    with patch("services.tools.geocoding_fallback._get_json", return_value=district_payload):
        assert _amap_city_district_adcodes("test-key", "广东省") is None


def test_amap_qps_limit_is_retried(monkeypatch):
    throttled = {"status": "0", "infocode": "10021", "info": "CUQPS_HAS_EXCEEDED_THE_LIMIT"}
    ok = {"status": "1", "pois": []}
    with (
        patch(
            "services.tools.geocoding_fallback._get_json", side_effect=[throttled, ok]
        ) as mock_get,
        patch("services.tools.geocoding_fallback.time.sleep") as mock_sleep,
    ):
        assert _get_amap_json("https://example", {}) == ok
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once()


@pytest.mark.unit
def test_overpass_tool_uses_amap_first_for_china(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    amap_features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [114.05, 22.55]},
            "properties": {"name": "深圳中学", "source": "Amap"},
        }
    ]
    location = OverpassLocation(display_name="深圳市", lat=22.5, lon=114.0, bbox=None)

    with (
        patch(
            "services.tools.geocoding._geocode_location_for_overpass",
            return_value=(location, None),
        ),
        patch(
            "services.tools.geocoding.search_amap_pois",
            return_value=amap_features,
        ) as mock_amap,
        patch(
            "services.tools.geocoding.create_feature_collection_geodata",
        ) as mock_store,
        patch("services.tools.geocoding.OverpassClient") as mock_overpass,
    ):
        layer = Mock()
        layer.name = "深圳市范围内 · School · 点"
        layer.id = "amap-layer-1"
        mock_store.return_value = layer

        state = {"messages": [], "geodata_results": []}
        result = geocode_using_overpass_to_geostate.func(
            state=state,
            tool_call_id="call-1",
            query="深圳的中学",
            amenity_key="school",
            location_name="深圳",
        )

    assert isinstance(result, Command)
    assert mock_amap.called
    assert mock_overpass.call_count == 0
    assert result.update["geodata_results"][0] is layer
    assert "Amap" in result.update["messages"][-1].content
    kwargs = mock_store.call_args.kwargs
    assert kwargs["data_source_id"] == "geocodeAmapCollection"
    assert kwargs["data_source"] == "Amap"


@pytest.mark.unit
def test_overpass_tool_falls_back_when_amap_empty(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    location = OverpassLocation(
        display_name="深圳市",
        lat=22.5,
        lon=114.0,
        osm_relation_id=3464353,
    )

    with (
        patch(
            "services.tools.geocoding._geocode_location_for_overpass",
            return_value=(location, None),
        ),
        patch("services.tools.geocoding.search_amap_pois", return_value=[]),
        patch.object(
            __import__("services.tools.geocoding", fromlist=["OverpassClient"]).OverpassClient,
            "execute_query",
            return_value=({"elements": []}, None),
        ),
    ):
        # Patch at instance path used inside the tool after OverpassClient()
        with patch("services.tools.geocoding.OverpassClient") as client_cls:
            client_cls.return_value.execute_query.return_value = ({"elements": []}, None)
            state = {"messages": [], "geodata_results": []}
            result = geocode_using_overpass_to_geostate.func(
                state=state,
                tool_call_id="call-2",
                query="深圳的中学",
                amenity_key="school",
                location_name="深圳",
            )

    assert isinstance(result, Command)
    assert "No 'School'" in result.update["messages"][-1].content
    client_cls.assert_called()


@pytest.mark.unit
def test_overseas_skips_amap_without_chinese_location(monkeypatch):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "test-key")
    location = OverpassLocation(display_name="Paris, France", lat=48.85, lon=2.35)

    with (
        patch(
            "services.tools.geocoding._geocode_location_for_overpass",
            return_value=(location, None),
        ),
        patch("services.tools.geocoding.search_amap_pois") as mock_amap,
        patch("services.tools.geocoding.OverpassClient") as client_cls,
    ):
        client_cls.return_value.execute_query.return_value = ({"elements": []}, None)
        state = {"messages": [], "geodata_results": []}
        geocode_using_overpass_to_geostate.func(
            state=state,
            tool_call_id="call-3",
            query="hospitals in Paris",
            amenity_key="hospital",
            location_name="Paris",
        )

    mock_amap.assert_not_called()
    client_cls.assert_called()
