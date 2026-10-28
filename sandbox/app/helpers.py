"""Reference helpers matching the preamble injected by ``runner._script_for``.

The sandbox executes an *inlined* copy of these helpers so agent code never
depends on importing this module. Keep signatures in sync with ``runner.py``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def get_layers(
    payload: Optional[Dict[str, Any]] = None, *, inputs: Optional[Dict[str, Any]] = None
):
    src = payload if payload is not None else inputs
    layers = src.get("layers") if isinstance(src, dict) else None
    return list(layers or [])


def find_layer(
    name: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
):
    layers = get_layers(payload)
    if not layers:
        return None
    if not name:
        return layers[0]
    needle = str(name).lower()
    for layer in layers:
        candidates = [
            str(layer.get("name") or ""),
            str(layer.get("title") or ""),
            str(layer.get("layer_id") or ""),
        ]
        if any(needle in c.lower() for c in candidates if c):
            return layer
    return None


def layer_geojson(layer: Optional[Dict[str, Any]]):
    if not layer:
        return None
    geojson = layer.get("geojson")
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except Exception:
            return None
    return geojson if isinstance(geojson, dict) else None


def layer_to_gdf(layer: Optional[Dict[str, Any]]):
    import geopandas as gpd

    geojson = layer_geojson(layer)
    if not geojson:
        raise ValueError(
            "Layer has no usable geojson. Check layer.get('error') / truncated."
        )
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features") or []
    elif geojson.get("type") == "Feature":
        features = [geojson]
    else:
        features = []
    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf = gpd.GeoDataFrame.from_features(features)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf


def load_gdfs(
    names: Optional[List[str]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    layers = get_layers(payload)
    out: Dict[str, Any] = {}
    if names:
        for name in names:
            layer = find_layer(name, payload)
            if layer is None:
                raise KeyError(f"Layer not found: {name}")
            key = layer.get("name") or layer.get("title") or name
            out[str(key)] = layer_to_gdf(layer)
        return out
    for layer in layers:
        key = layer.get("name") or layer.get("title") or layer.get("layer_id")
        if not key or (layer.get("geojson") is None and layer.get("error")):
            continue
        out[str(key)] = layer_to_gdf(layer)
    return out
