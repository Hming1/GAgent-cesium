"""
AI-powered map layer styling tools for the GeoAgent agent.
"""

import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from typing_extensions import Annotated

from models.geodata import GeoDataObject
from services.ai.automatic_styling import (
    detect_layer_type,
    generate_automatic_style,
    get_colorblind_safe_palette,
    get_colorbrewer_scheme,
    parse_color_scheme_request,
    parse_intelligent_color,
)
from services.tools.utils import (
    collect_stylable_layers,
    match_layer_names,
    promote_layers_to_map,
)

logger = logging.getLogger(__name__)


def _select_style_targets(
    state: Dict[str, Any],
    layer_names: Optional[List[str]] = None,
) -> List[Any]:
    """Pick layers to style: named match across map+results, else map, else results."""
    pool = collect_stylable_layers(state)
    if layer_names:
        return match_layer_names(pool, layer_names)

    map_layers = list(state.get("geodata_layers") or [])
    if map_layers:
        return map_layers
    return pool


def _style_command(
    *,
    state: Dict[str, Any],
    tool_call_id: str,
    tool_name: str,
    message: str,
    styled_layers: List[GeoDataObject],
) -> Command:
    """Build a Command that updates messages and promotes styled layers to the map."""
    update: Dict[str, Any] = {
        "messages": [
            *state["messages"],
            ToolMessage(name=tool_name, content=message, tool_call_id=tool_call_id),
        ]
    }
    if styled_layers:
        update.update(promote_layers_to_map(state, styled_layers))
    return Command(update=update)


def _empty_style_command(
    state: Dict[str, Any],
    tool_call_id: str,
    tool_name: str,
    message: str,
) -> Command:
    return Command(
        update={
            "messages": [
                *state["messages"],
                ToolMessage(name=tool_name, content=message, tool_call_id=tool_call_id),
            ]
        }
    )


def normalize_color(color: str) -> str:
    """
    Normalize color input to hex format.
    Now supports a wide range of color inputs including:
    - Basic color names (red, blue, etc.)
    - Web color names (forestgreen, dodgerblue, etc.)
    - Hex codes (#FF0000, FF0000, etc.)
    - ColorBrewer palette names (returns first color)

    Args:
        color: Color string to normalize (can be None or empty)

    Returns:
        Normalized hex color string, or None if input is None/empty
    """
    # Handle None and empty strings safely
    if not color or not isinstance(color, str):
        return color

    # Strip whitespace and special characters that might cause issues
    color = color.strip()
    if not color:
        return None

    # Use the intelligent color parsing system
    try:
        parsed_color = parse_intelligent_color(color)
        if parsed_color:
            return parsed_color
    except Exception as e:
        logger.warning(f"Failed to parse color '{color}': {e}. Using original value.")

    # If not recognized, return original (for backward compatibility)
    return color


@tool
def style_map_layers(
    state: Annotated[Dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    layer_names: Optional[List[str]] = None,
    fill_color: Optional[str] = None,
    stroke_color: Optional[str] = None,
    stroke_width: Optional[int] = None,
    fill_opacity: Optional[float] = None,
    stroke_opacity: Optional[float] = None,
    radius: Optional[int] = None,
    dash_pattern: Optional[str] = None,
) -> Command:
    """
    Style map layers with visual properties. Tool automatically provides current
    color context.

    CRITICAL: For colorblind-safe, accessibility, or distinguishable styling:
    - NEVER use one call without layer_names (this makes all layers identical!)
    - ALWAYS use separate calls: layer_names=["specific_layer"] with different
      colors
    - Each call must target ONE layer with a UNIQUE color combination

    COLOR SELECTION GUIDANCE - Use HEX colors (#RRGGBB format):

    WARM COLOR SCHEMES - Choose from diverse warm families:
    - Red family: #DC143C, #B22222, #8B0000, #CD5C5C
    - Orange family: #FF4500, #FF6347, #D2691E, #A0522D
    - Yellow family: #FFD700, #DAA520, #B8860B, #F4A460
    - Brown family: #A52A2A, #8B4513, #CD853F, #DEB887
    - Ensure HIGH CONTRAST between layers (avoid similar hues like #FFCC00 vs
      #FFB300)

    COOL COLOR SCHEMES - Choose from diverse cool families:
    - Blue family: #0000FF, #4169E1, #1E90FF, #87CEEB
    - Green family: #008000, #228B22, #32CD32, #90EE90
    - Purple family: #800080, #9370DB, #8A2BE2, #DDA0DD
    - Teal family: #008080, #20B2AA, #48D1CC, #AFEEEE

    COLORBLIND-SAFE SCHEMES - Use these proven combinations:
    - Orange: #E69F00, Sky Blue: #56B4E9, Green: #009E73
    - Yellow: #F0E442, Blue: #0072B2, Vermillion: #D55E00
    - Purple: #CC79A7, Grey: #999999

    EARTH TONE SCHEMES:
    - Browns: #8B4513, #A0522D, #CD853F, #DEB887
    - Greens: #556B2F, #6B8E23, #808000, #9ACD32
    - Tans: #D2B48C, #BC8F8F, #F5DEB3, #DDD8C7

    GENERAL PRINCIPLES:
    - Maintain 3:1 contrast ratio minimum between adjacent colors
    - Use darker stroke colors than fill colors for definition
    - Test color combinations for accessibility
    - Consider the map background when choosing colors
    - For 3+ layers, use colors from different families (red, blue, green, not
      red, pink, coral)

    For uniform appearance (all layers same color):
    - Use one call without layer_names
    - Example: style_map_layers(fill_color="#FF0000", stroke_color="#8B0000")

    Args:
        layer_names: Target specific layers (REQUIRED for distinguishable
                     styling)
        fill_color: Fill color as hex (#RRGGBB) - agent should choose
                    intelligently
        stroke_color: Border color as hex (#RRGGBB) - should be darker than
                     fill
        stroke_width: Border width in pixels
        fill_opacity: Fill transparency (0.0 to 1.0)
        stroke_opacity: Border transparency (0.0 to 1.0)
        radius: Point marker size
        dash_pattern: Line dash pattern like "5,5"
    """

    available_layers = collect_stylable_layers(state)
    if not available_layers:
        return _empty_style_command(
            state,
            tool_call_id,
            "style_map_layers",
            (
                "No layers are currently available to style. "
                "Load or generate a layer first "
                "(map layers, geodata_results, or geodata_last_results are all eligible)."
            ),
        )

    # Extract current colors for context (helps choose distinct colors)
    current_colors = []
    for layer in available_layers:
        if layer.style and layer.style.fill_color:
            fill = layer.style.fill_color
            stroke = layer.style.stroke_color or "none"
            current_colors.append(f"{layer.name}: fill={fill}, stroke={stroke}")

    color_context = (
        f"Current layer colors: {'; '.join(current_colors)}"
        if current_colors
        else "No existing colors to avoid."
    )

    logger.info(f"Available layers: {[layer.name for layer in available_layers]}")
    logger.info(f"Requested layer_names: {layer_names}")

    layers_to_style = _select_style_targets(state, layer_names)
    if layer_names and not layers_to_style:
        available_names = ", ".join([layer.name for layer in available_layers])
        return _empty_style_command(
            state,
            tool_call_id,
            "style_map_layers",
            (
                f"Could not find any layers matching the specified names. "
                f"Available layers: {available_names}"
            ),
        )

    logger.info(f"Layers selected for styling: {[layer.name for layer in layers_to_style]}")

    if not layers_to_style:
        available_names = ", ".join([layer.name for layer in available_layers])
        return _empty_style_command(
            state,
            tool_call_id,
            "style_map_layers",
            (
                f"Could not find any layers matching the specified names. "
                f"Available layers: {available_names}"
            ),
        )

    # Apply styling to selected layers
    styled_layers = []
    for layer in layers_to_style:
        # Create a copy of the layer
        layer_dict = layer.model_dump()

        # Build style parameters from the provided arguments
        style_params = {}

        if fill_color is not None:
            style_params["fill_color"] = normalize_color(fill_color)
        if stroke_color is not None:
            style_params["stroke_color"] = normalize_color(stroke_color)
        if stroke_width is not None:
            style_params["stroke_weight"] = stroke_width  # Note: stroke_weight
            # in the model
        if fill_opacity is not None:
            style_params["fill_opacity"] = fill_opacity
        if stroke_opacity is not None:
            style_params["stroke_opacity"] = stroke_opacity
        if radius is not None:
            style_params["radius"] = radius
        if dash_pattern is not None:
            style_params["stroke_dash_array"] = dash_pattern

        # Log the styling parameters being applied
        logger.info(f"Applying styling to layer '{layer.name}': {style_params}")

        # Initialize with defaults if no style exists
        if not layer_dict.get("style"):
            layer_dict["style"] = {
                "stroke_color": "#3388FF",
                "stroke_weight": 2,
                "stroke_opacity": 0.85,  # Changed from 1.0 to 0.85 (85%
                # opacity)
                "fill_color": "#3388FF",
                "fill_opacity": 0.15,  # Changed from 0.3 to 0.15 for less
                # transparency
                "radius": 6,  # Changed from 8 to 6
                "line_cap": "round",
                "line_join": "round",
            }

        # Update with the provided parameters
        layer_dict["style"].update(style_params)

        # Log the final style after update
        logger.info(f"Final style for layer '{layer.name}': {layer_dict['style']}")

        # Create new GeoDataObject
        updated_layer = GeoDataObject(**layer_dict)
        styled_layers.append(updated_layer)

    # Return success message and promote styled layers onto the map
    styled_layer_names = [layer.name for layer in layers_to_style]
    if len(styled_layer_names) == 1:
        message = (
            f"Successfully applied styling to layer '{styled_layer_names[0]}' "
            "and added/updated it on the map."
        )
    else:
        layer_list = ", ".join(styled_layer_names)
        message = (
            f"Successfully applied styling to {len(styled_layer_names)} layers: "
            f"{layer_list}. Layers were added/updated on the map."
        )

    message += f"\n\n{color_context}\n\n"

    return _style_command(
        state=state,
        tool_call_id=tool_call_id,
        tool_name="style_map_layers",
        message=message,
        styled_layers=styled_layers,
    )


@tool
def auto_style_new_layers(
    state: Annotated[Dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    layer_names: Optional[List[str]] = None,
) -> Command:
    """
    Automatically apply intelligent styling to newly uploaded layers with
    default colors.

    This tool directly applies appropriate cartographic colors based on layer
    names and descriptions,
    using the comprehensive automatic styling system that analyzes layer names
    and applies contextually
    appropriate colors and styles for different geographic feature types.

    Key examples: hospitals→red family, rivers→blue family, forests→green
    family, roads→gray family.

    Args:
        layer_names: Specific layer names to auto-style (if None, styles all
                     layers needing styling)
    """
    available_layers = collect_stylable_layers(state)

    if not available_layers:
        return _empty_style_command(
            state,
            tool_call_id,
            "auto_style_new_layers",
            "No layers are currently available to auto-style.",
        )

    # Determine which layers to auto-style
    if layer_names:
        layers_to_style = _select_style_targets(state, layer_names)
    else:
        candidates = _select_style_targets(state, None)
        layers_to_style = [
            layer
            for layer in candidates
            if not layer.style
            or (
                layer.style
                and layer.style.stroke_color in ["#3388FF", "#3388f", None]
                and layer.style.fill_color in ["#3388FF", "#3388f", None]
            )
        ]

    if not layers_to_style:
        return _empty_style_command(
            state,
            tool_call_id,
            "auto_style_new_layers",
            (
                "No layers found that need auto-styling. "
                "All layers appear to have custom styling already."
            ),
        )

    # Apply automatic styling using the comprehensive styling system
    styled_layers = []
    used_colors = set()

    # Extract existing colors to avoid conflicts
    for layer in available_layers:
        if layer.style and layer.style.fill_color and layer not in layers_to_style:
            used_colors.add(layer.style.fill_color.upper())

    for layer in layers_to_style:
        # Use the automatic styling system to generate appropriate styling
        layer_description = getattr(layer, "description", None) or getattr(layer, "title", None)
        geometry_type = getattr(layer, "geometry_type", None)

        auto_style = generate_automatic_style(
            layer_name=layer.name,
            layer_description=layer_description or "",
            geometry_type=geometry_type or "",
        )

        # Convert LayerStyle to dictionary for the layer
        layer_dict = layer.model_dump()
        layer_dict["style"] = {
            "stroke_color": auto_style.stroke_color,
            "fill_color": auto_style.fill_color,
            "stroke_weight": auto_style.stroke_weight,
            "fill_opacity": auto_style.fill_opacity,
            "stroke_opacity": auto_style.stroke_opacity,
            "radius": auto_style.radius,
            "stroke_dash_array": auto_style.stroke_dash_array,
            "line_cap": auto_style.line_cap,
            "line_join": auto_style.line_join,
        }

        # Remove None values
        layer_dict["style"] = {k: v for k, v in layer_dict["style"].items() if v is not None}

        # Track used colors - safe upper() calls
        if auto_style.fill_color:
            used_colors.add(auto_style.fill_color.upper())
        if auto_style.stroke_color:
            used_colors.add(auto_style.stroke_color.upper())

        styled_layer = GeoDataObject(**layer_dict)
        styled_layers.append(styled_layer)

    styled_layer_info = []
    for layer in styled_layers:
        layer_description = getattr(layer, "description", None) or getattr(layer, "title", None)
        layer_type = detect_layer_type(layer.name, layer_description or "")
        styled_layer_info.append(f"{layer.name} ({layer_type}): {layer.style.fill_color}")

    message = (
        f"Successfully applied intelligent automatic styling to {len(styled_layers)} "
        f"layer(s) and added/updated them on the map. Styling applied: "
        f"{'; '.join(styled_layer_info)}"
    )

    return _style_command(
        state=state,
        tool_call_id=tool_call_id,
        tool_name="auto_style_new_layers",
        message=message,
        styled_layers=styled_layers,
    )


@tool
def check_and_auto_style_layers(
    state: Annotated[Dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """
    Check for newly uploaded layers that have default styling (blue #3388ff colors) and need
    initial styling.

    IMPORTANT: This tool ONLY works for layers with default styling. Do NOT use this tool when:
    - Users want to change existing styled layers (use style_map_layers instead)
    - Users request colorblind-safe styling (use style_map_layers instead)
    - Users want to restyle any layers that already have custom colors (use style_map_layers
      instead)

    Only use this tool proactively when detecting newly uploaded layers that need initial styling.
    """
    available_layers = collect_stylable_layers(state)

    if not available_layers:
        return _empty_style_command(
            state,
            tool_call_id,
            "check_and_auto_style_layers",
            "No layers available for auto-styling.",
        )

    # Find layers that need styling (have default colors)
    layers_needing_style = [
        layer
        for layer in available_layers
        if not layer.style
        or (
            layer.style
            and layer.style.stroke_color in ["#3388FF", "#3388f", None]
            and layer.style.fill_color in ["#3388FF", "#3388f", None]
        )
    ]

    if not layers_needing_style:
        return Command(
            update={
                "messages": [
                    *state["messages"],
                    ToolMessage(
                        name="check_and_auto_style_layers",
                        content="All layers already have custom styling.",
                        tool_call_id=tool_call_id,
                    ),
                ]
            }
        )

    # Trigger auto-styling workflow
    layer_names = [layer.name for layer in layers_needing_style]
    message = (
        f"Detected {len(layers_needing_style)} newly uploaded layer(s) that need styling: "
        f"{', '.join(layer_names)}. "
        "Automatically applying intelligent cartographic styling based on layer names..."
    )

    return Command(
        update={
            "messages": [
                *state["messages"],
                ToolMessage(
                    name="check_and_auto_style_layers",
                    content=message,
                    tool_call_id=tool_call_id,
                ),
            ]
        }
    )


@tool
def apply_intelligent_color_scheme(
    state: Annotated[Dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    scheme_request: str,
    layer_names: Optional[List[str]] = None,
) -> Command:
    """
    Apply intelligent color schemes to layers based on natural language requests.

    Supports:
    - "colorblind safe" or "accessible" - applies colorblind-safe palette
    - "Set1", "Set2", "Spectral" - applies ColorBrewer schemes
    - "warm colors" - applies warm color palette
    - "cool colors" - applies cool color palette

    Each layer gets a unique color from the scheme to ensure distinguishability.

    Args:
        scheme_request: Natural language color scheme request
        layer_names: Specific layers to style (if None, styles all layers)
    """
    available_layers = collect_stylable_layers(state)

    if not available_layers:
        return _empty_style_command(
            state,
            tool_call_id,
            "apply_intelligent_color_scheme",
            (
                "No layers are currently available to apply color schemes to. "
                "Result layers are eligible; they will be promoted to the map when styled."
            ),
        )

    # Parse the color scheme request
    scheme_info = parse_color_scheme_request(scheme_request)

    if not scheme_info["colors"]:
        return _empty_style_command(
            state,
            tool_call_id,
            "apply_intelligent_color_scheme",
            f"Could not understand color scheme request: '{scheme_request}'",
        )

    layers_to_style = _select_style_targets(state, layer_names)
    if not layers_to_style:
        return _empty_style_command(
            state,
            tool_call_id,
            "apply_intelligent_color_scheme",
            "No matching layers found to style.",
        )

    # Apply colors from the scheme to layers (one solid color per layer)
    scheme_colors = scheme_info["colors"]
    styled_objects: List[GeoDataObject] = []
    styled_names: List[str] = []

    for i, layer in enumerate(layers_to_style):
        fill_color = scheme_colors[i % len(scheme_colors)]
        normalized_fill = normalize_color(fill_color)
        if normalized_fill and isinstance(normalized_fill, str):
            stroke_color = normalized_fill.replace("ff", "cc")
        else:
            stroke_color = fill_color

        layer_dict = layer.model_dump()
        if not layer_dict.get("style"):
            layer_dict["style"] = {}

        layer_dict["style"].update(
            {
                "fill_color": fill_color,
                "stroke_color": stroke_color,
                "fill_opacity": 0.6,
                "stroke_opacity": 1.0,
                "stroke_weight": 2,
            }
        )

        styled_objects.append(GeoDataObject(**layer_dict))
        styled_names.append(layer.name)

    message = (
        f"Successfully applied '{scheme_info['name']}' color scheme to "
        f"{len(styled_names)} layer(s): {', '.join(styled_names)} "
        f"(promoted to map). Description: {scheme_info['description']}"
    )

    return _style_command(
        state=state,
        tool_call_id=tool_call_id,
        tool_name="apply_intelligent_color_scheme",
        message=message,
        styled_layers=styled_objects,
    )


@tool
def color_layers_by_attribute(
    state: Annotated[Dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    field: str,
    layer_names: Optional[List[str]] = None,
    palette: str = "Set2",
    max_categories: int = 24,
) -> Command:
    """
    Color features inside one layer by an attribute field (categorical styling).

    Use this when the user asks to color by district / category / type within a
    single layer (e.g. "按区上色", "按 adname 分类上色"). This writes
    ``style.style_conditions[field].color_map`` and promotes the layer onto the
    map so Cesium can render per-feature colors.

    Do NOT use style_map_layers or apply_intelligent_color_scheme for
    within-layer attribute coloring — those only assign one solid color per layer.

    Args:
        field: Attribute field name (e.g. "adname", "type", "school").
        layer_names: Optional layer name/title filter; defaults to map layers or
            the only available result layer.
        palette: ColorBrewer-like name ("Set2", "Paired", "Spectral") or
            "colorblind".
        max_categories: Cap on distinct values colored (extras keep the layer
            default fill).
    """
    if not field or not str(field).strip():
        return _empty_style_command(
            state,
            tool_call_id,
            "color_layers_by_attribute",
            "Error: 'field' is required (e.g. adname, type).",
        )

    field = str(field).strip()
    layers_to_style = _select_style_targets(state, layer_names)
    if not layers_to_style:
        return _empty_style_command(
            state,
            tool_call_id,
            "color_layers_by_attribute",
            ("No layers available to color by attribute. " "Generate or load a layer first."),
        )

    # Prefer a single target layer for categorical styling.
    if len(layers_to_style) > 1 and not layer_names:
        layers_to_style = layers_to_style[:1]

    palette_key = (palette or "Set2").strip().lower()
    styled_objects: List[GeoDataObject] = []
    summaries: List[str] = []

    for layer in layers_to_style:
        try:
            value_counts, available_fields = _attribute_value_counts(layer.data_link, field)
        except Exception as exc:  # noqa: BLE001
            return _empty_style_command(
                state,
                tool_call_id,
                "color_layers_by_attribute",
                f"Failed to load layer '{layer.name}' data: {exc}",
            )

        if value_counts is None:
            available = ", ".join(str(c) for c in (available_fields or [])[:40])
            return _empty_style_command(
                state,
                tool_call_id,
                "color_layers_by_attribute",
                (
                    f"Field '{field}' not found on layer '{layer.name}'. "
                    f"Available fields (sample): {available}"
                ),
            )

        categories = [item[0] for item in value_counts[: max(1, max_categories)]]
        n_colors = max(len(categories), 1)

        if palette_key in {"colorblind", "accessible", "safe"}:
            colors = get_colorblind_safe_palette(n_colors)
        else:
            scheme_name = {
                "set1": "Set1",
                "set2": "Set2",
                "set3": "Set3",
                "paired": "Paired",
                "spectral": "Spectral",
                "dark2": "Dark2",
                "accent": "Accent",
            }.get(palette_key, palette if palette else "Set2")
            colors = get_colorbrewer_scheme(scheme_name, n_colors) or get_colorblind_safe_palette(
                n_colors
            )

        color_map = {category: colors[i % len(colors)] for i, category in enumerate(categories)}

        layer_dict = layer.model_dump()
        existing_style = layer_dict.get("style") or {}
        existing_conditions = dict(existing_style.get("style_conditions") or {})
        existing_conditions[field] = {"color_map": color_map}
        existing_style.update(
            {
                "stroke_color": existing_style.get("stroke_color") or "#2c3e50",
                "stroke_weight": existing_style.get("stroke_weight") or 1.5,
                "stroke_opacity": existing_style.get("stroke_opacity") or 1.0,
                "fill_opacity": existing_style.get("fill_opacity") or 0.75,
                "radius": existing_style.get("radius") or 6,
                "style_conditions": existing_conditions,
            }
        )
        # Keep a neutral default fill for values outside the color_map.
        if not existing_style.get("fill_color"):
            existing_style["fill_color"] = "#94a3b8"
        layer_dict["style"] = existing_style
        styled_objects.append(GeoDataObject(**layer_dict))

        preview = ", ".join(f"{k}={v}" for k, v in list(color_map.items())[:8])
        extra = len(value_counts) - len(categories)
        extra_note = f" (+{extra} unmapped values keep default fill)" if extra > 0 else ""
        summaries.append(
            f"'{layer.name}' by '{field}': {len(categories)} categories{extra_note}. "
            f"Sample: {preview}"
        )

    message = (
        "Applied categorical attribute coloring and promoted layer(s) to the map. "
        + " | ".join(summaries)
    )
    return _style_command(
        state=state,
        tool_call_id=tool_call_id,
        tool_name="color_layers_by_attribute",
        message=message,
        styled_layers=styled_objects,
    )


def _attribute_value_counts(data_link: str, field: str):
    """Return [(value, count), ...] sorted by count desc, plus available field names.

    Prefers a lightweight GeoJSON parse to avoid heavy GIS drivers in simple cases.
    Returns ``(None, available_fields)`` when the field is missing.
    """
    import json
    import os
    from collections import Counter
    from urllib.parse import urlparse

    from services.tools.attribute_tools import BASE_URL, LOCAL_UPLOAD_DIR, _load_gdf

    local_path = None
    if data_link.startswith(f"{BASE_URL}/uploads/") or data_link.startswith(
        f"{BASE_URL}/api/stream/"
    ):
        local_path = os.path.join(LOCAL_UPLOAD_DIR, os.path.basename(urlparse(data_link).path))
    elif os.path.isfile(data_link):
        local_path = data_link

    if (
        local_path
        and os.path.isfile(local_path)
        and local_path.lower().endswith((".geojson", ".json"))
    ):
        with open(local_path, encoding="utf-8") as handle:
            payload = json.load(handle)
        features = payload.get("features") if isinstance(payload, dict) else None
        if isinstance(features, list):
            available: set = set()
            counter: Counter = Counter()
            for feature in features:
                props = (feature or {}).get("properties") or {}
                if isinstance(props, dict):
                    available.update(str(k) for k in props.keys())
                    if field in props:
                        raw = props.get(field)
                        key = "(空)" if raw is None else str(raw)
                        counter[key] += 1
            if field not in available and not counter:
                return None, sorted(available)
            return counter.most_common(), sorted(available)

    gdf = _load_gdf(data_link)
    available_fields = [str(c) for c in gdf.columns]
    if field not in gdf.columns:
        return None, available_fields
    series = gdf[field].fillna("(空)").astype(str)
    return list(series.value_counts().items()), available_fields


def _detect_layers_needing_styling(available_layers):
    """Helper function to detect layers that need styling (used for testing)."""
    return [
        layer
        for layer in available_layers
        if not layer.style
        or (
            layer.style
            and layer.style.stroke_color in ["#3388FF", "#3388f", None]
            and layer.style.fill_color in ["#3388FF", "#3388ff", None]
        )
    ]
