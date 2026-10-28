"""Tests for urban inefficient-space identification."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, box
from starlette.testclient import TestClient

from services.inefficient_space.analyzer import analyze_inefficient_space, get_presets
from services.inefficient_space.enrichment import enrich_with_poi_counts
from services.inefficient_space.field_mapping import apply_field_mapping, classify_land_use_family
from services.inefficient_space.rules import classify_feature
from services.inefficient_space.schemas import (
    AnalyzeRequest,
    FieldMapping,
    ThresholdBundle,
)


def test_classify_land_use_family():
    assert classify_land_use_family("一类工业用地") == "industrial"
    assert classify_land_use_family("商业服务业用地") == "commercial"
    assert classify_land_use_family("二类居住用地") == "residential"
    assert classify_land_use_family("闲置空地") == "idle_vacant"
    assert classify_land_use_family("unknown-xyz") is None


def test_idle_vacant_by_near_zero_development():
    result = classify_feature(
        {"far": 0.01, "building_density": 0.02, "idle_years": 0, "land_use": "商业"},
        ThresholdBundle(),
        ["idle_vacant", "industrial", "commercial", "residential"],
    )
    assert result["is_inefficient"] is True
    assert result["inefficient_type"] == "idle_vacant"
    assert "near_zero_development" in result["matched_rules"]


def test_industrial_low_far_and_tax():
    result = classify_feature(
        {
            "far": 0.4,
            "building_density": 0.5,
            "idle_years": 0,
            "tax_output": 10,
            "land_use": "工业用地",
        },
        ThresholdBundle(),
        ["idle_vacant", "industrial", "commercial", "residential"],
    )
    assert result["is_inefficient"] is True
    assert result["inefficient_type"] == "industrial"
    assert "low_far" in result["matched_rules"]
    assert "low_tax_output" in result["matched_rules"]


def test_efficient_when_thresholds_not_met():
    result = classify_feature(
        {
            "far": 2.5,
            "building_density": 0.6,
            "idle_years": 0,
            "tax_output": 500,
            "land_use": "工业用地",
        },
        ThresholdBundle(),
        ["idle_vacant", "industrial", "commercial", "residential"],
    )
    assert result["is_inefficient"] is False
    assert result["inefficient_type"] == "efficient"


def test_apply_field_mapping_aliases():
    gdf = gpd.GeoDataFrame(
        {
            "容积率": [0.5],
            "建筑密度": [0.2],
            "用地性质": ["工业"],
            "geometry": [box(0, 0, 1, 1)],
        },
        crs=4326,
    )
    mapped = apply_field_mapping(
        gdf, FieldMapping(far="容积率", building_density="建筑密度", land_use="用地性质")
    )
    assert float(mapped.iloc[0]["far"]) == 0.5
    assert mapped.iloc[0]["land_use"] == "工业"


def test_enrich_with_poi_counts():
    parcels = gpd.GeoDataFrame(
        {"id": [1], "geometry": [box(0, 0, 2, 2)]},
        crs=4326,
    )
    poi = gpd.GeoDataFrame(
        {"name": ["a", "b", "c"], "geometry": [Point(0.5, 0.5), Point(1.5, 1.5), Point(5, 5)]},
        crs=4326,
    )
    enriched = enrich_with_poi_counts(parcels, poi)
    assert int(enriched.iloc[0]["poi_count"]) == 2


@pytest.fixture()
def parcel_geojson_path():
    """Write fixture GeoJSON under the repo tests dir (avoid OS temp / pyogrio)."""
    features = [
        {
            "type": "Feature",
            "properties": {
                "far": 0.02,
                "building_density": 0.01,
                "idle_years": 0,
                "tax_output": 0,
                "land_use": "空地",
            },
            "geometry": box(0, 0, 1, 1).__geo_interface__,
        },
        {
            "type": "Feature",
            "properties": {
                "far": 0.3,
                "building_density": 0.2,
                "idle_years": 1,
                "tax_output": 20,
                "land_use": "工业用地",
            },
            "geometry": box(1, 0, 2, 1).__geo_interface__,
        },
        {
            "type": "Feature",
            "properties": {
                "far": 2.0,
                "building_density": 0.55,
                "idle_years": 0,
                "tax_output": 300,
                "land_use": "工业用地",
            },
            "geometry": box(2, 0, 3, 1).__geo_interface__,
        },
    ]
    out_dir = Path(__file__).resolve().parent / "_fixtures"
    out_dir.mkdir(exist_ok=True)
    parcel_path = out_dir / "inefficient_parcels.geojson"
    parcel_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    yield parcel_path
    if parcel_path.exists():
        parcel_path.unlink()


def test_analyze_end_to_end(parcel_geojson_path, monkeypatch):
    stored = {}

    def fake_store_file(name: str, content: bytes):
        stored["name"] = name
        stored["content"] = content
        return "http://localhost:8000/api/stream/fake.geojson", "fake-id"

    monkeypatch.setattr(
        "services.inefficient_space.analyzer.store_file",
        fake_store_file,
    )

    response = analyze_inefficient_space(
        AnalyzeRequest(
            parcel_data_link=str(parcel_geojson_path),
            include_non_match=False,
        )
    )
    assert response.summary.matched >= 2
    assert response.layer.data_link.endswith("fake.geojson")
    assert response.layer.style is not None
    assert "inefficient_type" in response.layer.style.style_conditions

    fc = json.loads(stored["content"].decode("utf-8"))
    types = {f["properties"]["inefficient_type"] for f in fc["features"]}
    assert "idle_vacant" in types
    assert "industrial" in types
    assert "efficient" not in types


def test_presets_endpoint():
    presets = get_presets()
    assert "industrial" in presets.enabled_types
    assert presets.type_colors["commercial"] == "#e67e22"
    assert "工业" in presets.land_use_hints["industrial"]


def test_api_presets_and_analyze(parcel_geojson_path, monkeypatch):
    from main import app

    monkeypatch.setattr(
        "services.inefficient_space.analyzer.store_file",
        lambda name, content: ("http://localhost:8000/api/stream/x.geojson", "x"),
    )

    client = TestClient(app)
    presets_resp = client.get("/api/inefficient-space/presets")
    assert presets_resp.status_code == 200
    assert "thresholds" in presets_resp.json()

    analyze_resp = client.post(
        "/api/inefficient-space/analyze",
        json={"parcel_data_link": str(parcel_geojson_path)},
    )
    assert analyze_resp.status_code == 200
    body = analyze_resp.json()
    assert body["summary"]["matched"] >= 1
    assert body["layer"]["name"]
