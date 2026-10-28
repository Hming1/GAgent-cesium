import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict


DEFAULT_MAX_SECONDS = int(os.getenv("SANDBOX_MAX_SECONDS", "30"))
DEFAULT_MAX_OUTPUT_BYTES = int(os.getenv("SANDBOX_MAX_OUTPUT_BYTES", str(1024 * 1024)))


def _truncate_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return value
    truncated = encoded[:max_bytes].decode("utf-8", errors="replace")
    return f"{truncated}\n...[truncated to {max_bytes} bytes]"


def _safe_env() -> Dict[str, str]:
    env = {
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PATH": os.environ.get("PATH", ""),
    }
    # Forward proxy and pip settings for internet download capabilities
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "PIP_INDEX_URL",
        "PIP_TRUSTED_HOST",
    ]:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


SANDBOX_HELPERS_VERSION = "2"


def _script_for(code: str) -> str:
    # Helpers are inlined so agent code does not need to guess the payload shape.
    # Common mistake: treating `inputs` as {layer_name: geojson}. Real shape is
    # {analysis_goal, layers: [SandboxLayerInput...], params}.
    # Rebuild the analysis-sandbox image after changing this preamble.
    return f"""
import json
from pathlib import Path

SANDBOX_HELPERS_VERSION = "{SANDBOX_HELPERS_VERSION}"


def _json_default(value):
    try:
        import numpy as np
        if isinstance(value, np.generic):
            return value.item()
    except Exception:
        pass
    try:
        import pandas as pd
        if isinstance(value, (pd.Timestamp,)):
            return value.isoformat()
    except Exception:
        pass
    return str(value)


def get_layers(payload=None):
    src = payload if payload is not None else inputs
    layers = src.get("layers") if isinstance(src, dict) else None
    return list(layers or [])


def find_layer(name=None, payload=None):
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


def layer_geojson(layer):
    if not layer:
        return None
    geojson = layer.get("geojson")
    if isinstance(geojson, str):
        try:
            geojson = json.loads(geojson)
        except Exception:
            return None
    return geojson if isinstance(geojson, dict) else None


def layer_to_gdf(layer):
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


def load_gdfs(names=None, payload=None):
    layers = get_layers(payload)
    out = {{}}
    if names:
        for name in names:
            layer = find_layer(name, payload)
            if layer is None:
                raise KeyError(f"Layer not found: {{name}}")
            key = layer.get("name") or layer.get("title") or name
            out[str(key)] = layer_to_gdf(layer)
        return out
    for layer in layers:
        key = layer.get("name") or layer.get("title") or layer.get("layer_id")
        if not key or (layer.get("geojson") is None and layer.get("error")):
            continue
        out[str(key)] = layer_to_gdf(layer)
    return out


with open("inputs.json", "r", encoding="utf-8") as _inputs_file:
    _payload = json.load(_inputs_file)

inputs = {{
    "analysis_goal": _payload.get("analysis_goal", ""),
    "layers": _payload.get("layers", []),
    "params": _payload.get("params", {{}}),
}}
params = inputs["params"]
result = None
geojson_outputs = []
artifacts = []

{code}

# Normalize geojson_outputs: agents often pass gdf.to_json() (str).
_normalized_geojson = []
for _item in geojson_outputs or []:
    if not isinstance(_item, dict):
        continue
    _gj = _item.get("geojson")
    if isinstance(_gj, str):
        try:
            _gj = json.loads(_gj)
        except Exception:
            pass
        _item = dict(_item)
        _item["geojson"] = _gj
    _normalized_geojson.append(_item)
geojson_outputs = _normalized_geojson

Path("result.json").write_text(
    json.dumps(
        {{
            "result": result,
            "geojson_outputs": geojson_outputs,
            "artifacts": artifacts,
            "helpers_version": SANDBOX_HELPERS_VERSION,
        }},
        default=_json_default,
    ),
    encoding="utf-8",
)
"""


def execute_python(payload: Dict[str, Any]) -> Dict[str, Any]:
    code = payload.get("code") or ""
    layers = payload.get("layers") or []
    max_seconds = int(payload.get("max_seconds") or DEFAULT_MAX_SECONDS)
    max_output_bytes = int(payload.get("max_output_bytes") or DEFAULT_MAX_OUTPUT_BYTES)

    if not code.strip():
        layer_names = [layer.get("title") or layer.get("name") for layer in layers]
        return {
            "ok": True,
            "summary": (
                "Python analysis sandbox is available "
                f"(helpers v{SANDBOX_HELPERS_VERSION}). "
                f"Received {len(layers)} layer(s): {', '.join(filter(None, layer_names))}."
            ),
            "stdout": "",
            "stderr": "",
            "result": {
                "layer_count": len(layers),
                "layers": layer_names,
                "helpers_version": SANDBOX_HELPERS_VERSION,
            },
            "artifacts": [],
            "geojson_outputs": [],
        }

    # Prefer OS temp dir so local Windows pytest can exercise the runner;
    # Docker sandbox images still mount /tmp writable.
    with tempfile.TemporaryDirectory(
        prefix="nalamap-analysis-",
        dir=tempfile.gettempdir(),
    ) as workdir:
        workdir_path = Path(workdir)
        (workdir_path / "inputs.json").write_text(
            json.dumps(payload, default=str),
            encoding="utf-8",
        )
        (workdir_path / "analysis.py").write_text(_script_for(code), encoding="utf-8")

        try:
            completed = subprocess.run(
                [sys.executable, "analysis.py"],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=max_seconds,
                env=_safe_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "summary": "Python analysis timed out.",
                "stdout": _truncate_text(exc.stdout or "", max_output_bytes),
                "stderr": _truncate_text(exc.stderr or "", max_output_bytes),
                "result": None,
                "artifacts": [],
                "geojson_outputs": [],
                "error": f"Execution exceeded {max_seconds} seconds.",
            }

        stdout = _truncate_text(completed.stdout or "", max_output_bytes)
        stderr = _truncate_text(completed.stderr or "", max_output_bytes)

        result_path = workdir_path / "result.json"
        result_payload: Dict[str, Any] = {}
        if result_path.exists():
            try:
                result_payload = json.loads(result_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                stderr = f"{stderr}\nFailed to parse result.json: {exc}".strip()

        ok = completed.returncode == 0
        return {
            "ok": ok,
            "summary": (
                "Python analysis completed."
                if ok
                else f"Python analysis failed with exit code {completed.returncode}."
            ),
            "stdout": stdout,
            "stderr": stderr,
            "result": result_payload.get("result"),
            "artifacts": result_payload.get("artifacts") or [],
            "geojson_outputs": result_payload.get("geojson_outputs") or [],
            "error": (
                None if ok else f"Process exited with code {completed.returncode}."
            ),
        }
