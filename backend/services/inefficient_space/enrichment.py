"""Optional POI / enterprise spatial enrichment for parcels."""

from __future__ import annotations

import logging
from typing import Optional

import geopandas as gpd
import pandas as pd

from services.inefficient_space.field_mapping import resolve_column
from services.inefficient_space.schemas import FieldMapping

logger = logging.getLogger(__name__)


def enrich_with_poi_counts(parcels: gpd.GeoDataFrame, poi: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add poi_count by counting POI points that intersect each parcel."""
    if parcels.empty or poi.empty:
        out = parcels.copy()
        out["poi_count"] = 0
        return out

    left = parcels.copy()
    right = poi.copy()
    if left.crs is None:
        left = left.set_crs(4326)
    if right.crs is None:
        right = right.set_crs(4326)
    if left.crs != right.crs:
        right = right.to_crs(left.crs)

    left = left.reset_index(drop=True)
    left["_parcel_idx"] = left.index
    try:
        joined = gpd.sjoin(
            left[["_parcel_idx", "geometry"]], right, how="left", predicate="intersects"
        )
        counts = joined.groupby("_parcel_idx").size()
        # Prefer non-null joins so unmatched left rows are not counted as hits.
        if "index_right" in joined.columns:
            counts = joined.dropna(subset=["index_right"]).groupby("_parcel_idx").size()
        left["poi_count"] = left["_parcel_idx"].map(counts).fillna(0).astype(int)
    except Exception as exc:
        logger.warning("POI enrichment failed: %s", exc)
        left["poi_count"] = 0
    return left.drop(columns=["_parcel_idx"], errors="ignore")


def enrich_with_enterprise_tax(
    parcels: gpd.GeoDataFrame,
    enterprises: gpd.GeoDataFrame,
    mapping: FieldMapping,
) -> gpd.GeoDataFrame:
    """Spatially join enterprise tax values onto parcels (sum of intersecting)."""
    if parcels.empty or enterprises.empty:
        return parcels.copy()

    left = parcels.copy()
    right = enterprises.copy()
    if left.crs is None:
        left = left.set_crs(4326)
    if right.crs is None:
        right = right.set_crs(4326)
    if left.crs != right.crs:
        right = right.to_crs(left.crs)

    tax_col = resolve_column(
        [str(c) for c in right.columns],
        mapping.enterprise_tax_field,
        ["tax_output", "税收产出", "税收", "tax", "tax_per_mu"],
    )
    if tax_col is None:
        logger.warning("Enterprise layer has no recognizable tax field; skip enrichment")
        return left

    left = left.reset_index(drop=True)
    left["_parcel_idx"] = left.index
    try:
        joined = gpd.sjoin(
            left[["_parcel_idx", "geometry"]],
            right[[tax_col, "geometry"]],
            how="left",
            predicate="intersects",
        )
        tax_sum = (
            joined.dropna(subset=[tax_col])
            .groupby("_parcel_idx")[tax_col]
            .apply(lambda s: pd.to_numeric(s, errors="coerce").fillna(0).sum())
        )
        # Only fill tax_output when missing or zero on the parcel.
        existing = pd.to_numeric(left.get("tax_output"), errors="coerce")
        mapped = left["_parcel_idx"].map(tax_sum)
        if "tax_output" not in left.columns:
            left["tax_output"] = mapped
        else:
            left["tax_output"] = existing.where(existing.notna() & (existing > 0), mapped)
    except Exception as exc:
        logger.warning("Enterprise enrichment failed: %s", exc)

    return left.drop(columns=["_parcel_idx"], errors="ignore")


def maybe_enrich(
    parcels: gpd.GeoDataFrame,
    mapping: FieldMapping,
    poi: Optional[gpd.GeoDataFrame] = None,
    enterprises: Optional[gpd.GeoDataFrame] = None,
) -> gpd.GeoDataFrame:
    out = parcels
    if poi is not None:
        out = enrich_with_poi_counts(out, poi)
    else:
        out = out.copy()
        if "poi_count" not in out.columns:
            out["poi_count"] = None
    if enterprises is not None:
        out = enrich_with_enterprise_tax(out, enterprises, mapping)
    return out
