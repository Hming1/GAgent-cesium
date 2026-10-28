import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from typing_extensions import Annotated

from core.config import (
    PYTHON_ANALYSIS_MAX_FEATURES_PER_LAYER,
    PYTHON_ANALYSIS_MAX_OUTPUT_BYTES,
)
from models.geodata import DataOrigin, DataType, GeoDataObject
from models.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResponse,
    SandboxGeoJSONOutput,
    SandboxLayerInput,
)
from models.states import GeoDataAgentState
from services.sandbox.client import SandboxClientError, execute_python_analysis
from services.storage.file_management import store_file
from services.tools.attribute_tools import _fc_from_gdf, _load_gdf, _slug
from services.tools.utils import resolve_input_layers

logger = logging.getLogger(__name__)

# Hard cap on sandbox executions per chat session. The system prompt asks the
# model to stop after repeated failures, but that is advisory only. Without a
# hard stop a failing sandbox run is retried until LangGraph hits its recursion
# limit, which surfaces to users as a generic 500 error.
# Allow a couple of recovery attempts after a bad first script, without
# letting the agent burn the whole recursion budget on sandbox retries.
PYTHON_ANALYSIS_MAX_CALLS = int(os.getenv("PYTHON_ANALYSIS_MAX_CALLS", "5"))
_SANDBOX_CALL_COUNTS: Dict[str, int] = {}

# Injected into agent code so outdated analysis-sandbox images (without the
# runner preamble helpers) still expose find_layer / layer_to_gdf.
_SANDBOX_HELPERS_FALLBACK = r"""
# --- geoagent helpers fallback (safe if already defined by sandbox preamble) ---
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
            import json as _json
            geojson = _json.loads(geojson)
        except Exception:
            return None
    return geojson if isinstance(geojson, dict) else None


def layer_to_gdf(layer):
    import geopandas as gpd
    geojson = layer_geojson(layer)
    if not geojson:
        raise ValueError("Layer has no usable geojson. Check layer.get('error') / truncated.")
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
    out = {}
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
# --- end helpers fallback ---
"""


def _with_helpers_fallback(code: str) -> str:
    """Prepend helpers so agent code works even on older sandbox images."""
    body = (code or "").strip()
    if not body:
        return ""
    if "def find_layer" in body:
        return body
    return f"{_SANDBOX_HELPERS_FALLBACK}\n{body}\n"


def _select_layers(
    state: GeoDataAgentState,
    layer_names: Optional[List[str]],
) -> List[GeoDataObject]:
    # Named lookup also searches geodata_results so freshly clipped/buffered
    # layers are visible without an explicit add_layers_to_map first.
    if layer_names:
        return resolve_input_layers(state, layer_names)
    return list(resolve_input_layers(state))


def _serialize_layer(
    layer: GeoDataObject,
    max_features: int,
) -> SandboxLayerInput:
    metadata = {
        "data_source": layer.data_source,
        "description": layer.description,
        "llm_description": layer.llm_description,
        "bounding_box": layer.bounding_box,
        "properties": layer.properties or {},
    }

    payload = SandboxLayerInput(
        layer_id=layer.id,
        data_source_id=layer.data_source_id,
        name=layer.name,
        title=layer.title,
        data_link=layer.data_link,
        layer_type=layer.layer_type,
        metadata=metadata,
    )

    try:
        gdf = _load_gdf(layer.data_link)
        feature_count = len(gdf)
        sample_gdf = gdf.head(max_features) if feature_count > max_features else gdf
        payload.geojson = _fc_from_gdf(sample_gdf, keep_geometry=True)
        payload.feature_count = feature_count
        payload.sent_feature_count = len(sample_gdf)
        payload.truncated = feature_count > len(sample_gdf)
    except Exception as exc:
        logger.info("Layer %s could not be serialized for sandbox: %s", layer.name, exc)
        payload.error = str(exc)

    return payload


def _store_geojson_output(
    output: SandboxGeoJSONOutput,
    analysis_goal: str,
) -> GeoDataObject:
    title = output.title or output.name or "Python analysis result"
    slug = _slug(title) or "python-analysis-result"
    filename = f"{slug}_{uuid.uuid4().hex[:8]}.geojson"
    content = json.dumps(output.geojson).encode("utf-8")
    url, _ = store_file(filename, content)

    description = output.description or f"Python analysis output for: {analysis_goal}"

    return GeoDataObject(
        id=uuid.uuid4().hex,
        data_source_id="python_analysis",
        data_type=DataType.GEOJSON,
        data_origin=DataOrigin.TOOL,
        data_source="GeoAgentPythonAnalysis",
        data_link=url,
        name=slug,
        title=title,
        description=description,
        llm_description=description,
        score=0.2,
        bounding_box=None,
        layer_type="GeoJSON",
        properties={"analysis_goal": analysis_goal},
    )


def _build_tool_message(
    response: SandboxExecutionResponse,
    created_layers: List[GeoDataObject],
    *,
    truncated_layers: Optional[List[str]] = None,
) -> str:
    parts = []
    if response.summary:
        parts.append(response.summary)
    if response.result is not None:
        parts.append(f"Result: {json.dumps(response.result, default=str)}")
    if response.stdout:
        parts.append(f"stdout:\n{response.stdout.strip()}")
    if response.stderr:
        parts.append(f"stderr:\n{response.stderr.strip()}")
        if "find_layer" in response.stderr and "not defined" in response.stderr:
            parts.append(
                "HINT: analysis-sandbox image is outdated (helpers missing). "
                "Rebuild with: docker compose up --build analysis-sandbox. "
                "Meanwhile prefer geoprocess operation='area' then attribute_tool2 sort_by."
            )
    if response.error:
        parts.append(f"Sandbox error: {response.error}")
    if truncated_layers:
        parts.append(
            "WARNING: these layers were truncated before sandbox execution: "
            f"{truncated_layers}. Raise max_features_per_layer and retry once if "
            "the analysis needs the full feature set. "
            "API reminder: use find_layer()/layer_to_gdf(), not inputs[layer_name]."
        )
    if created_layers:
        layer_info = [
            {
                "id": layer.id,
                "name": layer.name,
                "title": layer.title,
                "data_link": layer.data_link,
            }
            for layer in created_layers
        ]
        parts.append(
            "Created GeoJSON layer(s) in geodata_results: " f"{json.dumps(layer_info, default=str)}"
        )
    if not parts:
        parts.append("Python analysis sandbox completed without textual output.")
    return "\n\n".join(parts)


def _session_key(state: Any) -> str:
    """Best-effort session identifier used to scope the sandbox call budget."""
    options = state.get("options") if hasattr(state, "get") else None
    session_id = getattr(options, "session_id", None)
    if not session_id and isinstance(options, dict):
        session_id = options.get("session_id")
    return str(session_id or "unknown")


def _sandbox_budget_exceeded(state: Any, tool_call_id: str) -> Optional[Command]:
    """Refuse further sandbox runs once the per-session budget is exhausted.

    The system prompt already tells the model to stop after repeated tool
    failures, but models do not reliably comply. Without a hard stop the agent
    can retry the sandbox dozens of times and eventually trip LangGraph's
    recursion limit, turning a recoverable failure into a 500.
    """
    if PYTHON_ANALYSIS_MAX_CALLS <= 0:
        return None
    key = _session_key(state)
    used = _SANDBOX_CALL_COUNTS.get(key, 0)
    if used < PYTHON_ANALYSIS_MAX_CALLS:
        _SANDBOX_CALL_COUNTS[key] = used + 1
        return None
    logger.warning(
        "Python sandbox call budget exhausted for session %s (%d/%d)",
        key,
        used,
        PYTHON_ANALYSIS_MAX_CALLS,
    )
    return Command(
        update={
            "messages": [
                ToolMessage(
                    name="run_python_analysis",
                    content=(
                        f"Error: python sandbox call budget exhausted "
                        f"({used}/{PYTHON_ANALYSIS_MAX_CALLS}) for this session. "
                        "Do NOT call run_python_analysis again. Stop retrying and tell "
                        "the user what could not be computed, then propose an "
                        "alternative (use the geoprocess tool, or ask the user to "
                        "add/upload the required layer)."
                    ),
                    tool_call_id=tool_call_id,
                    status="error",
                )
            ]
        }
    )


async def _run_python_analysis_tool(
    state: GeoDataAgentState,
    tool_call_id: str,
    analysis_goal: str,
    code: str = "",
    layer_names: Optional[List[str]] = None,
    params: Optional[Dict[str, Any]] = None,
    max_features_per_layer: Optional[int] = None,
    max_seconds: Optional[int] = None,
) -> Union[Dict[str, Any], Command]:
    budget_stop = _sandbox_budget_exceeded(state, tool_call_id)
    if budget_stop is not None:
        return budget_stop

    max_features = max_features_per_layer or PYTHON_ANALYSIS_MAX_FEATURES_PER_LAYER
    selected_layers = _select_layers(state, layer_names)
    serialized_layers = [_serialize_layer(layer, max_features) for layer in selected_layers]

    request = SandboxExecutionRequest(
        analysis_goal=analysis_goal,
        code=_with_helpers_fallback(code or ""),
        layers=serialized_layers,
        params=params or {},
        max_seconds=max_seconds,
        max_output_bytes=PYTHON_ANALYSIS_MAX_OUTPUT_BYTES,
    )

    try:
        response = await execute_python_analysis(request)
    except SandboxClientError as exc:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        name="run_python_analysis",
                        content=str(exc),
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    created_layers = []
    for output in response.geojson_outputs:
        try:
            created_layers.append(_store_geojson_output(output, analysis_goal))
        except Exception as exc:
            logger.warning("Failed to store sandbox GeoJSON output %s: %s", output.name, exc)

    truncated = [
        layer.title or layer.name
        for layer in serialized_layers
        if getattr(layer, "truncated", False)
    ]
    new_results = (state.get("geodata_results") or []) + created_layers
    message = _build_tool_message(response, created_layers, truncated_layers=truncated or None)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    name="run_python_analysis",
                    content=message,
                    tool_call_id=tool_call_id,
                )
            ],
            "geodata_results": new_results,
        }
    )


@tool
async def run_python_analysis(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    analysis_goal: str,
    code: str = "",
    layer_names: Optional[List[str]] = None,
    params: Optional[Dict[str, Any]] = None,
    max_features_per_layer: Optional[int] = None,
    max_seconds: Optional[int] = None,
) -> Union[Dict[str, Any], Command]:
    """
    Run bounded Python/pandas/geopandas analysis in the isolated sandbox.

    Prefer dedicated GeoAgent tools for simple filter/summary/buffer/clip.
    Use this for geometry area ranking, custom stats, or derived GeoJSON that
    those tools cannot produce.

    Sandbox API (do NOT treat inputs as {{layer_name: geojson}}):
      inputs = {{
        "analysis_goal": str,
        "layers": [ {{name, title, layer_id, geojson, feature_count, truncated, error, ...}} ],
        "params": dict,
      }}
      params = inputs["params"]
      Helpers already injected:
        get_layers() / find_layer(name) / layer_geojson(layer) /
        layer_to_gdf(layer) / load_gdfs([name, ...])
      Set `result` to a JSON-serializable object. Append map outputs via
        geojson_outputs.append({{"name","title","description","geojson"}}).

    Minimal example (area Top-N in EPSG:32650):
      layer = find_layer("Parks Clipped by Buffer") or find_layer()
      gdf = layer_to_gdf(layer).to_crs("EPSG:32650")
      gdf["area_m2"] = gdf.geometry.area
      top = gdf.nlargest(5, "area_m2")[["name", "area_m2"]]
      result = {{"total": len(gdf), "top5": top.to_dict(orient="records")}}

    Args:
        analysis_goal: Plain-language objective.
        code: Python to execute using the API above.
        layer_names: Layer names/titles to serialize (map + results). Omit to
            send all current layers. Raise max_features_per_layer if the layer
            is truncated (check layer["truncated"]).
        params: Optional JSON parameters for the code.
        max_features_per_layer: Cap on features per layer (default from env).
        max_seconds: Execution timeout seconds.

    Returns:
        Command updating messages and optional geodata_results.
    """
    return await _run_python_analysis_tool(
        state=state,
        tool_call_id=tool_call_id,
        analysis_goal=analysis_goal,
        code=code,
        layer_names=layer_names,
        params=params,
        max_features_per_layer=max_features_per_layer,
        max_seconds=max_seconds,
    )
