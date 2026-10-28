"""
Clip operation: clip one layer by the geometry of another.
"""

import json
import logging
from typing import Any, Dict, List

import geopandas as gpd

from services.tools.geoprocessing.utils import flatten_features
from services.tools.geoprocessing.projection_utils import (
    prepare_gdf_for_operation,
    OperationType,
)

logger = logging.getLogger(__name__)


def op_clip(
    layers: List[Dict[str, Any]],
    crs: str = "EPSG:3857",
    auto_optimize_crs: bool = False,
    projection_metadata: bool = False,
    override_crs: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Clip the first layer by the geometry of the second layer.

    This operation clips (cuts) the features of the first layer using the
    boundary of the second layer. Only the parts of features from the first
    layer that fall within the second layer are retained.

    Args:
        layers: List of exactly 2 GeoJSON layers. The first layer will be
                clipped by the second layer.
        crs: Working CRS for the operation (default EPSG:3857)

    Returns:
        A list containing a single FeatureCollection with clipped features
    """
    if len(layers) < 2:
        logger.warning("op_clip requires at least 2 layers")
        return layers

    if len(layers) > 2:
        logger.warning(f"op_clip received {len(layers)} layers, using only first 2")

    # Layer to be clipped (target)
    target_layer = layers[0]
    # Layer to clip by (mask)
    mask_layer = layers[1]

    # A clip mask must bound an area. Passing a point layer as the mask is a
    # caller mistake (usually swapped arguments); fail with an actionable message
    # instead of letting shapely raise a cryptic type error deep inside.
    mask_geoms = [(f.get("geometry") or {}).get("type") for f in (mask_layer.get("features") or [])]
    area_types = {"Polygon", "MultiPolygon"}
    if mask_geoms and not any(t in area_types for t in mask_geoms):
        raise ValueError(
            "clip requires a polygon mask, but the second layer contains "
            f"{sorted({t for t in mask_geoms if t})}. "
            "Ensure the polygon boundary layer is passed as the mask (second layer)."
        )

    try:
        # Convert target layer to GeoDataFrame
        target_features = flatten_features([target_layer])
        if not target_features:
            return [{"type": "FeatureCollection", "features": []}]

        target_gdf = gpd.GeoDataFrame.from_features(target_features)
        if target_gdf.crs is None:
            target_gdf.set_crs("EPSG:4326", inplace=True)

        # Prepare target with smart CRS selection
        target_gdf, target_crs_info = prepare_gdf_for_operation(
            target_gdf,
            OperationType.CLIP,
            auto_optimize_crs=auto_optimize_crs,
            override_crs=override_crs or (None if crs == "EPSG:3857" else crs),
        )

        # Convert mask layer to GeoDataFrame
        mask_features = flatten_features([mask_layer])
        if not mask_features:
            return [{"type": "FeatureCollection", "features": []}]

        mask_gdf = gpd.GeoDataFrame.from_features(mask_features)
        if mask_gdf.crs is None:
            mask_gdf.set_crs("EPSG:4326", inplace=True)

        # Ensure mask is in same CRS as target
        mask_gdf, mask_crs_info = prepare_gdf_for_operation(
            mask_gdf,
            OperationType.CLIP,
            auto_optimize_crs=False,
            override_crs=target_crs_info.get("epsg_code"),
        )

        # Combine all mask geometries into one
        from shapely.ops import unary_union

        mask_geometry = unary_union(mask_gdf.geometry)

        # Clip the target layer
        clipped_gdf = target_gdf.clip(mask_geometry)

        # If result is empty, return empty FeatureCollection
        if clipped_gdf.empty:
            return [{"type": "FeatureCollection", "features": []}]

        # Reproject back to EPSG:4326
        clipped_gdf = clipped_gdf.to_crs("EPSG:4326")

        # Convert to GeoJSON
        fc = json.loads(clipped_gdf.to_json())
        if projection_metadata and isinstance(fc, dict):
            if "properties" not in fc:
                fc["properties"] = {}
            fc["properties"]["_crs_metadata"] = {
                "target": target_crs_info,
                "mask": mask_crs_info,
            }
        return [fc]

    except Exception as exc:
        # Do not swallow: a genuine failure must not look like "the clip matched
        # nothing" (which is a legitimate, reportable result).
        logger.exception(f"Error in op_clip: {exc}")
        raise
