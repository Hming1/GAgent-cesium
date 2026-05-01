import json
import logging
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
from services.tools.utils import match_layer_names

logger = logging.getLogger(__name__)


def _select_layers(
    state: GeoDataAgentState,
    layer_names: Optional[List[str]],
) -> List[GeoDataObject]:
    layers = list(state.get("geodata_layers") or [])
    if not layer_names:
        return layers
    return match_layer_names(layers, layer_names)


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
        data_source="NaLaMapPythonAnalysis",
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
    if response.error:
        parts.append(f"Sandbox error: {response.error}")
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
    max_features = max_features_per_layer or PYTHON_ANALYSIS_MAX_FEATURES_PER_LAYER
    selected_layers = _select_layers(state, layer_names)
    serialized_layers = [_serialize_layer(layer, max_features) for layer in selected_layers]

    request = SandboxExecutionRequest(
        analysis_goal=analysis_goal,
        code=code or "",
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

    new_results = (state.get("geodata_results") or []) + created_layers
    message = _build_tool_message(response, created_layers)

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
    Run bounded Python data analysis in the isolated analysis sandbox.

    Use this tool only when the user explicitly asks for Python/pandas-style
    analysis, custom calculations, exploratory data analysis, or a derived
    GeoJSON layer that is not covered by existing geoprocessing or attribute
    tools. Prefer dedicated NaLaMap tools for simple filtering, summaries,
    styling, geocoding, and standard spatial operations.

    Args:
        analysis_goal: Plain-language description of the analysis objective.
        code: Optional Python code to execute. The sandbox exposes `inputs`,
            `params`, `result`, `geojson_outputs`, and `artifacts`. Set `result`
            to a JSON-serializable object and append GeoJSON outputs as
            {"name": str, "title": str, "description": str, "geojson": dict}.
        layer_names: Optional names/titles of current map layers to send. If
            omitted, all current layers are considered, but only GeoJSON-like
            layers that can be loaded are serialized.
        params: Optional JSON parameters for the code.
        max_features_per_layer: Optional cap on serialized features per layer.
        max_seconds: Optional sandbox execution timeout in seconds.

    Returns:
        Command updating messages and, when GeoJSON outputs are returned,
        geodata_results.
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
