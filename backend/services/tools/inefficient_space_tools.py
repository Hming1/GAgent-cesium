"""Agent tools for urban inefficient-space identification."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from typing_extensions import Annotated

from models.geodata import GeoDataObject
from models.states import GeoDataAgentState
from services.inefficient_space.analyzer import analyze_inefficient_space, get_presets
from services.inefficient_space.field_mapping import TYPE_LABELS, infer_mapping_from_columns
from services.inefficient_space.schemas import AnalyzeRequest, FieldMapping, ThresholdBundle
from services.tools.attribute_tools import _load_gdf
from services.tools.utils import match_layer_names

logger = logging.getLogger(__name__)


def _collect_layers(state: GeoDataAgentState) -> List[Any]:
    layers: List[Any] = []
    for key in ("geodata_layers", "geodata_results", "geodata_last_results"):
        for layer in state.get(key) or []:
            if layer not in layers:
                layers.append(layer)
    return layers


def _resolve_layer(
    state: GeoDataAgentState,
    layer_name: Optional[str] = None,
    data_link: Optional[str] = None,
) -> Optional[Any]:
    layers = _collect_layers(state)
    if data_link:
        for layer in layers:
            link = getattr(layer, "data_link", None)
            if isinstance(layer, dict):
                link = layer.get("data_link")
            if link == data_link:
                return layer
    if layer_name:
        matched = match_layer_names(layers, [layer_name])
        if matched:
            return matched[0]
    if layers and not layer_name and not data_link:
        # Prefer currently selected map layers.
        map_layers = state.get("geodata_layers") or []
        if map_layers:
            return map_layers[0]
    return None


def _layer_link(layer: Any) -> Optional[str]:
    if layer is None:
        return None
    if isinstance(layer, dict):
        return layer.get("data_link")
    return getattr(layer, "data_link", None)


def _layer_name(layer: Any) -> str:
    if isinstance(layer, dict):
        return layer.get("title") or layer.get("name") or "layer"
    return getattr(layer, "title", None) or getattr(layer, "name", "layer")


def _error_command(tool_name: str, tool_call_id: str, content: str) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    name=tool_name,
                    content=content,
                    tool_call_id=tool_call_id,
                    status="error",
                )
            ]
        }
    )


@tool
def get_inefficient_presets(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Union[Dict[str, Any], Command]:
    """
    Return default inefficient-space field mapping, thresholds, type labels and colors.

    Use this before configuring or explaining urban inefficient-space analysis,
    or when the user asks about default 容积率/建筑密度/闲置年限/税收 thresholds.
    """
    presets = get_presets()
    payload = presets.model_dump()
    return Command(
        update={
            "messages": [
                ToolMessage(
                    name="get_inefficient_presets",
                    content=json.dumps(payload, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )


@tool
def infer_inefficient_field_mapping(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    parcel_layer_name: Optional[str] = None,
    parcel_data_link: Optional[str] = None,
) -> Union[Dict[str, Any], Command]:
    """
    Infer attribute field mapping for inefficient-space indicators from a parcel layer.

    Maps source columns onto far / building_density / idle_years / tax_output / land_use.
    If critical fields are missing, returns exactly one clarifying_question the agent
    should ask the user. Call this after the parcel layer is loaded and before analyze.
    """
    layer = _resolve_layer(state, parcel_layer_name, parcel_data_link)
    if layer is None:
        return _error_command(
            "infer_inefficient_field_mapping",
            tool_call_id,
            "未找到地块图层。请先用 PostGIS/上传加载地块，或提供 parcel_layer_name。",
        )

    link = _layer_link(layer)
    if not link:
        return _error_command(
            "infer_inefficient_field_mapping",
            tool_call_id,
            f"图层「{_layer_name(layer)}」缺少 data_link，无法读取字段。",
        )

    try:
        gdf = _load_gdf(link)
    except Exception as exc:
        logger.exception("Failed to load parcel layer for field inference")
        return _error_command(
            "infer_inefficient_field_mapping",
            tool_call_id,
            f"无法加载地块图层字段：{exc}",
        )

    columns = [str(c) for c in gdf.columns if str(c).lower() != "geometry"]
    inferred = infer_mapping_from_columns(columns)
    inferred["parcel_layer_name"] = _layer_name(layer)
    inferred["parcel_data_link"] = link

    return Command(
        update={
            "messages": [
                ToolMessage(
                    name="infer_inefficient_field_mapping",
                    content=json.dumps(inferred, ensure_ascii=False),
                    tool_call_id=tool_call_id,
                )
            ]
        }
    )


@tool
def analyze_inefficient_space_tool(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    parcel_layer_name: Optional[str] = None,
    parcel_data_link: Optional[str] = None,
    poi_layer_name: Optional[str] = None,
    enterprise_layer_name: Optional[str] = None,
    field_mapping: Optional[Dict[str, Any]] = None,
    thresholds: Optional[Dict[str, Any]] = None,
    enabled_types: Optional[List[str]] = None,
    include_non_match: bool = False,
    result_name: Optional[str] = None,
    city_name: Optional[str] = None,
    add_to_map: bool = True,
) -> Union[Dict[str, Any], Command]:
    """
    Run urban inefficient-space classification on a parcel vector layer.

    Identifies idle vacant land and industrial / commercial / residential
    inefficient parcels using FAR, building density, idle years, tax output and
    land-use rules. Prefer infer_inefficient_field_mapping first when field names
    are unknown. Optional POI / enterprise layers enrich the analysis.

    Args:
        parcel_layer_name: Name/title of the parcel layer in current state.
        parcel_data_link: Explicit data_link if known.
        poi_layer_name: Optional POI layer for activity enrichment.
        enterprise_layer_name: Optional enterprise layer for tax enrichment.
        field_mapping: Optional override mapping of indicator fields.
        thresholds: Optional threshold overrides by type.
        enabled_types: Subset of idle_vacant/industrial/commercial/residential.
        include_non_match: Keep non-inefficient features in the result layer.
        result_name: Output layer name.
        city_name: Optional city label used to suggest a memory note for local defaults.
        add_to_map: Also add the result to geodata_layers when true.
    """
    parcel = _resolve_layer(state, parcel_layer_name, parcel_data_link)
    if parcel is None:
        return _error_command(
            "analyze_inefficient_space_tool",
            tool_call_id,
            "未找到地块图层。请先加载 PostGIS/上传地块，或指定 parcel_layer_name。",
        )

    parcel_link = _layer_link(parcel)
    if not parcel_link:
        return _error_command(
            "analyze_inefficient_space_tool",
            tool_call_id,
            f"地块图层「{_layer_name(parcel)}」缺少 data_link。",
        )

    poi_link = None
    if poi_layer_name:
        poi = _resolve_layer(state, poi_layer_name, None)
        poi_link = _layer_link(poi)

    enterprise_link = None
    if enterprise_layer_name:
        enterprise = _resolve_layer(state, enterprise_layer_name, None)
        enterprise_link = _layer_link(enterprise)

    try:
        mapping_model = (
            FieldMapping.model_validate(field_mapping) if field_mapping else FieldMapping()
        )
        threshold_model = (
            ThresholdBundle.model_validate(thresholds) if thresholds else ThresholdBundle()
        )
        request = AnalyzeRequest(
            parcel_data_link=parcel_link,
            poi_data_link=poi_link,
            enterprise_data_link=enterprise_link,
            field_mapping=mapping_model,
            thresholds=threshold_model,
            enabled_types=enabled_types
            or ["idle_vacant", "industrial", "commercial", "residential"],
            include_non_match=include_non_match,
            result_name=result_name or "低效空间判别结果",
        )
        response = analyze_inefficient_space(request)
    except Exception as exc:
        logger.exception("Agent inefficient-space analysis failed")
        return _error_command(
            "analyze_inefficient_space_tool",
            tool_call_id,
            f"低效空间判别失败：{exc}",
        )

    layer: GeoDataObject = response.layer
    summary = response.summary.model_dump()
    by_type_lines = []
    for key, stats in (summary.get("by_type") or {}).items():
        count = stats.get("count") or 0
        if count <= 0:
            continue
        label = TYPE_LABELS.get(key, key)
        area = stats.get("area_sqm") or 0
        by_type_lines.append(f"- {label}: {count} 个, 面积约 {area:.0f} m²")

    memory_suggestion = None
    if city_name:
        memory_suggestion = (
            f"{city_name}低效空间默认阈值："
            f"{json.dumps(threshold_model.model_dump(), ensure_ascii=False)}"
        )

    content = {
        "operation": "analyze_inefficient_space",
        "parcel_layer": _layer_name(parcel),
        "result_layer_id": layer.id,
        "result_layer_name": layer.name,
        "data_link": layer.data_link,
        "summary": summary,
        "type_breakdown": by_type_lines,
        "memory_suggestion": memory_suggestion,
        "message": (
            f"完成低效空间判别：输入 {summary.get('total', 0)} 个要素，"
            f"命中 {summary.get('matched', 0)} 个。"
            + ("\n" + "\n".join(by_type_lines) if by_type_lines else "")
        ),
    }

    update: Dict[str, Any] = {
        "messages": [
            ToolMessage(
                name="analyze_inefficient_space_tool",
                content=json.dumps(content, ensure_ascii=False),
                tool_call_id=tool_call_id,
            )
        ],
        "geodata_results": (state.get("geodata_results") or []) + [layer],
        "geodata_last_results": [layer],
        "results_title": "低效空间判别结果",
    }
    if add_to_map:
        update["geodata_layers"] = (state.get("geodata_layers") or []) + [layer]

    return Command(update=update)
