"""Sandbox preamble helpers must expose the documented layer API."""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sandbox.app.runner import _script_for, execute_python  # noqa: E402


def test_script_preamble_defines_layer_helpers():
    script = _script_for("result = {'ok': True}")
    assert "def find_layer(" in script
    assert "def layer_to_gdf(" in script
    assert "def load_gdfs(" in script
    assert "inputs = {" in script
    assert '"layers"' in script


def test_execute_python_with_helper_area_topn():
    pytest.importorskip("geopandas")
    payload = {
        "analysis_goal": "top parks by area",
        "layers": [
            {
                "layer_id": "l1",
                "data_source_id": "test",
                "name": "parks-clipped-by-buffer",
                "title": "Parks Clipped by Buffer",
                "geojson": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "small"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [114.0, 22.5],
                                        [114.001, 22.5],
                                        [114.001, 22.501],
                                        [114.0, 22.501],
                                        [114.0, 22.5],
                                    ]
                                ],
                            },
                        },
                        {
                            "type": "Feature",
                            "properties": {"name": "large"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [114.0, 22.5],
                                        [114.01, 22.5],
                                        [114.01, 22.51],
                                        [114.0, 22.51],
                                        [114.0, 22.5],
                                    ]
                                ],
                            },
                        },
                    ],
                },
            }
        ],
        "params": {},
        "code": """
layer = find_layer("Parks Clipped by Buffer")
gdf = layer_to_gdf(layer).to_crs("EPSG:32650")
gdf["area_m2"] = gdf.geometry.area
top = gdf.nlargest(1, "area_m2")[["name", "area_m2"]]
result = {"top1": top.to_dict(orient="records")}
""",
        "max_seconds": 30,
    }
    out = execute_python(payload)
    assert out["ok"] is True, out.get("stderr")
    assert out["result"]["top1"][0]["name"] == "large"
    assert out["result"]["top1"][0]["area_m2"] > 0


def test_python_analysis_max_calls_env_default():
    # Documented default is recovery-friendly (5), not the old hard 3.
    from services.tools import python_analysis_tool as pat

    assert pat.PYTHON_ANALYSIS_MAX_CALLS >= 5 or os.getenv("PYTHON_ANALYSIS_MAX_CALLS")
