"""Orchestrate inefficient-space loading, enrichment, scoring and persistence."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

import geopandas as gpd
import pandas as pd

from models.geodata import DataOrigin, DataType, GeoDataObject, LayerStyle, ProcessingMetadata
from services.inefficient_space.enrichment import maybe_enrich
from services.inefficient_space.field_mapping import (
    TYPE_COLORS,
    TYPE_LABELS,
    apply_field_mapping,
)
from services.inefficient_space.rules import classify_feature
from services.inefficient_space.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    AnalyzeSummary,
    InefficientSpacePresets,
    FieldMapping,
    ThresholdBundle,
    TypeSummary,
)
from services.storage.file_management import store_file
from services.tools.attribute_tools import _load_gdf

logger = logging.getLogger(__name__)


def get_presets() -> InefficientSpacePresets:
    from services.inefficient_space.field_mapping import LAND_USE_HINTS

    return InefficientSpacePresets(
        field_mapping=FieldMapping(),
        thresholds=ThresholdBundle(),
        enabled_types=["idle_vacant", "industrial", "commercial", "residential"],
        land_use_hints=LAND_USE_HINTS,
        type_labels=TYPE_LABELS,
        type_colors=TYPE_COLORS,
    )


def _feature_area_sqm(geom) -> float:
    if geom is None or geom.is_empty:
        return 0.0
    try:
        # Approximate geodesic area via equal-area projection when CRS is geographic.
        series = gpd.GeoSeries([geom], crs=4326)
        return float(series.to_crs(3857).area.iloc[0])
    except Exception:
        try:
            return float(geom.area)
        except Exception:
            return 0.0


def _build_result_style() -> LayerStyle:
    return LayerStyle(
        stroke_color="#2c3e50",
        stroke_weight=1.5,
        stroke_opacity=1.0,
        fill_opacity=0.65,
        style_conditions={
            "inefficient_type": {
                "color_map": dict(TYPE_COLORS),
            }
        },
    )


def analyze_inefficient_space(request: AnalyzeRequest) -> AnalyzeResponse:
    parcels = _load_gdf(request.parcel_data_link)
    if parcels is None or parcels.empty:
        raise ValueError("地块图层为空或无法加载")

    if parcels.crs is None:
        parcels = parcels.set_crs(4326)
    else:
        parcels = parcels.to_crs(4326)

    mapped = apply_field_mapping(parcels, request.field_mapping)
    # Keep geometry from original after attribute copy.
    if "geometry" not in mapped.columns and "geometry" in parcels.columns:
        mapped = gpd.GeoDataFrame(mapped, geometry=parcels.geometry, crs=parcels.crs)
    elif not isinstance(mapped, gpd.GeoDataFrame):
        mapped = gpd.GeoDataFrame(mapped, geometry=parcels.geometry, crs=parcels.crs)

    poi_gdf: Optional[gpd.GeoDataFrame] = None
    enterprise_gdf: Optional[gpd.GeoDataFrame] = None
    if request.poi_data_link:
        poi_gdf = _load_gdf(request.poi_data_link)
    if request.enterprise_data_link:
        enterprise_gdf = _load_gdf(request.enterprise_data_link)

    enriched = maybe_enrich(
        mapped,
        request.field_mapping,
        poi=poi_gdf,
        enterprises=enterprise_gdf,
    )

    records = []
    by_type: Dict[str, TypeSummary] = {
        key: TypeSummary() for key in ["idle_vacant", "industrial", "commercial", "residential"]
    }
    matched_count = 0
    total_area = 0.0
    matched_area = 0.0

    for _, row in enriched.iterrows():
        attrs = row.drop(labels=["geometry"], errors="ignore").to_dict()
        result = classify_feature(attrs, request.thresholds, request.enabled_types)
        area = _feature_area_sqm(row.geometry)
        total_area += area

        if result["is_inefficient"]:
            matched_count += 1
            matched_area += area
            t = result["inefficient_type"]
            if t not in by_type:
                by_type[t] = TypeSummary()
            by_type[t].count += 1
            by_type[t].area_sqm += area
        elif not request.include_non_match:
            continue

        props: Dict[str, Any] = dict(attrs)
        props.update(result)
        props["inefficient_type_label"] = TYPE_LABELS.get(
            result["inefficient_type"], result["inefficient_type"]
        )
        props["area_sqm"] = area
        # Convert non-JSON-safe values.
        for key, value in list(props.items()):
            if pd.isna(value) if not isinstance(value, (list, dict)) else False:
                props[key] = None
            elif hasattr(value, "item"):
                try:
                    props[key] = value.item()
                except Exception:
                    props[key] = str(value)

        records.append(
            {"type": "Feature", "geometry": row.geometry.__geo_interface__, "properties": props}
        )

    feature_collection = {"type": "FeatureCollection", "features": records}
    content = json.dumps(feature_collection, ensure_ascii=False).encode("utf-8")
    result_name = request.result_name or "低效空间判别结果"
    url, file_id = store_file(f"{result_name}.geojson", content)

    layer = GeoDataObject(
        id=str(uuid.uuid4()),
        data_source_id="inefficient_space",
        data_type=DataType.GEOJSON,
        data_origin=DataOrigin.TOOL.value if hasattr(DataOrigin.TOOL, "value") else "tool",
        data_source="inefficient_space",
        data_link=url,
        name=result_name,
        title=result_name,
        description="城市低效空间判别结果",
        layer_type="GeoJson",
        visible=True,
        style=_build_result_style(),
        processing_metadata=ProcessingMetadata(
            operation="inefficient_space_analyze",
            crs_used="EPSG:4326",
            crs_name="WGS 84",
            auto_selected=True,
            selection_reason="Canonical CRS for map display",
            origin_layers=[request.parcel_data_link],
        ),
        properties={
            "file_id": file_id,
            "matched": str(matched_count),
        },
    )

    summary = AnalyzeSummary(
        total=len(enriched),
        matched=matched_count,
        by_type=by_type,
        area_stats={
            "total_area_sqm": total_area,
            "matched_area_sqm": matched_area,
        },
    )
    return AnalyzeResponse(layer=layer, summary=summary)
