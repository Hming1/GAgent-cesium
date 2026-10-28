import json
import logging
from typing import Any, Dict, List

import geopandas as gpd
from services.tools.geoprocessing.projection_utils import (
    prepare_gdf_for_operation,
    OperationType,
)

logger = logging.getLogger(__name__)


def _to_gdf(layer: Dict[str, Any], role: str) -> gpd.GeoDataFrame:
    """Build a GeoDataFrame with an active geometry column.

    A layer without usable geometry features would otherwise raise deep inside
    ``set_crs`` and be misreported downstream as "no matches", which looks like a
    legitimate empty spatial join.
    """
    features = layer.get("features") or []
    if not features:
        raise ValueError(f"{role} layer has no features to join")
    gdf = gpd.GeoDataFrame.from_features(features)
    if gdf.empty or "geometry" not in gdf.columns:
        raise ValueError(f"{role} layer produced no geometry column")
    gdf = gdf.set_geometry("geometry")
    gdf.set_crs("EPSG:4326", inplace=True, allow_override=True)
    return gdf


def op_sjoin(
    layers: List[Dict[str, Any]],
    how: str = "inner",
    predicate: str = "intersects",
    auto_optimize_crs: bool = False,
    projection_metadata: bool = False,
    override_crs: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Perform a spatial join between two layers.
    - layers: expects exactly two FeatureCollections (left, right).
    - how: 'left', 'right', or 'inner'.
    - predicate: spatial predicate, e.g. 'intersects', 'contains', 'within'.

    Errors propagate to the caller: returning ``[]`` on failure made genuine
    exceptions indistinguishable from "the join matched nothing".
    """
    if len(layers) < 2:
        return layers
    left_gdf = _to_gdf(layers[0], "left")
    right_gdf = _to_gdf(layers[1], "right")

    if auto_optimize_crs:
        left_prepared, left_info = prepare_gdf_for_operation(
            left_gdf,
            OperationType.SJOIN,
            auto_optimize_crs=auto_optimize_crs,
            override_crs=override_crs,
        )
        right_prepared, right_info = prepare_gdf_for_operation(
            right_gdf,
            OperationType.SJOIN,
            auto_optimize_crs=False,
            override_crs=left_info.get("epsg_code"),
        )

        joined = gpd.sjoin(left_prepared, right_prepared, how=how, predicate=predicate)
        fc = json.loads(joined.to_json())
        if projection_metadata and isinstance(fc, dict):
            if "properties" not in fc:
                fc["properties"] = {}
            fc["properties"]["_crs_metadata"] = {"left": left_info, "right": right_info}
        return [fc]
    else:
        # Legacy behavior: operate in EPSG:4326
        joined = gpd.sjoin(left_gdf, right_gdf, how=how, predicate=predicate)
        return [json.loads(joined.to_json())]
