import difflib
from typing import Any, Dict, List, Optional, Sequence


def _iter_result_layers(state: Any) -> List[Any]:
    """Collect unique layers from result collections (current + previous turn)."""
    layers: List[Any] = []
    seen = set()
    for source in ("geodata_results", "geodata_last_results"):
        for item in state.get(source) or []:
            layer_id = getattr(item, "id", None)
            if layer_id is not None:
                if layer_id in seen:
                    continue
                seen.add(layer_id)
            if getattr(item, "data_link", None):
                layers.append(item)
    return layers


def resolve_input_layers(
    state: Any,
    layer_names: Optional[List[str]] = None,
    *,
    include_results: bool = True,
) -> List[Any]:
    """Resolve layers that a processing tool may consume.

    Processing tools (geoprocess / attribute / python analysis) used to read only
    ``geodata_layers`` (layers explicitly added to the map), while most producing
    tools wrote their output to ``geodata_results`` only. A freshly geocoded
    boundary therefore could not be processed without the user adding it to the
    map by hand first.

    This helper keeps map layers as the primary source of truth and falls back to
    the result collections **when no map layers exist at all**. When
    ``layer_names`` is provided and the map is non-empty, result collections are
    also searched so a freshly produced layer can be addressed by name without
    forcing the model to re-geocode.

    Two result collections are consulted on fallback:

    * ``geodata_results`` - results produced during the current request.
    * ``geodata_last_results`` - results carried over from the previous turn.
      The frontend resends its last results under this key, and
      ``geodata_results`` is reset to ``[]`` for every new request, so without
      this a follow-up question about a layer the user never added to the map
      ("buffer that boundary you just made") cannot be answered.

    Args:
        state: Agent state containing ``geodata_layers`` / ``geodata_results`` /
            ``geodata_last_results``.
        layer_names: Optional names/titles to match (fuzzy, see match_layer_names).
        include_results: Allow falling back to the result collections when the
            map has no layers.

    Returns:
        List of layer objects, possibly filtered by ``layer_names``.
    """
    layers: List[Any] = list(state.get("geodata_layers") or [])

    if include_results:
        if not layers:
            # Empty map: consume current/previous tool results so
            # "geocode then process" works without a manual map click.
            layers = _iter_result_layers(state)
        elif layer_names:
            # Named lookup with a non-empty map: also search results.
            # Otherwise a freshly geocoded POI layer in geodata_results is
            # invisible behind older map layers, and the model re-geocodes
            # / re-describes until recursion_limit.
            by_id: Dict[Any, Any] = {
                getattr(layer, "id", None): layer
                for layer in layers
                if getattr(layer, "id", None) is not None
            }
            orphans = [layer for layer in layers if getattr(layer, "id", None) is None]
            for item in _iter_result_layers(state):
                item_id = getattr(item, "id", None)
                if item_id is None:
                    orphans.append(item)
                elif item_id not in by_id:
                    by_id[item_id] = item
            layers = list(by_id.values()) + orphans

    if layer_names:
        return match_layer_names(layers, layer_names)
    return layers


def collect_stylable_layers(
    state: Any,
    layer_names: Optional[List[str]] = None,
) -> List[Any]:
    """Collect layers that styling tools may target.

    Unlike :func:`resolve_input_layers`, styling merges map layers with result
    collections so a freshly geocoded / filtered layer can be styled and promoted
    to the map without requiring the user to click it first. Map entries win when
    the same id appears in both places.
    """
    by_id: Dict[Any, Any] = {}
    orphan: List[Any] = []

    for source in ("geodata_layers", "geodata_results", "geodata_last_results"):
        for item in state.get(source) or []:
            if not getattr(item, "data_link", None):
                continue
            layer_id = getattr(item, "id", None)
            if layer_id is None:
                orphan.append(item)
                continue
            # First write wins: geodata_layers is consulted first.
            if layer_id not in by_id:
                by_id[layer_id] = item

    layers: List[Any] = list(by_id.values()) + orphan
    if layer_names:
        return match_layer_names(layers, layer_names)
    return layers


def promote_layers_to_map(
    state: Any,
    layers: Sequence[Any],
) -> Dict[str, Any]:
    """Merge ``layers`` into ``geodata_layers`` and refresh matching result entries.

    Returns a state-update dict suitable for merging into a LangGraph ``Command``.
    """
    styled_by_id = {
        getattr(layer, "id", None): layer
        for layer in layers
        if getattr(layer, "id", None) is not None
    }
    map_by_id: Dict[Any, Any] = {
        getattr(layer, "id", None): layer
        for layer in (state.get("geodata_layers") or [])
        if getattr(layer, "id", None) is not None
    }
    for layer_id, layer in styled_by_id.items():
        map_by_id[layer_id] = layer

    update: Dict[str, Any] = {"geodata_layers": list(map_by_id.values())}

    for key in ("geodata_results", "geodata_last_results"):
        collection = list(state.get(key) or [])
        if not collection:
            continue
        changed = False
        refreshed: List[Any] = []
        for item in collection:
            item_id = getattr(item, "id", None)
            if item_id in styled_by_id:
                refreshed.append(styled_by_id[item_id])
                changed = True
            else:
                refreshed.append(item)
        if changed:
            update[key] = refreshed

    return update


def match_layer_names(layers: List[Any], target_names: List[str], cutoff: float = 0.6) -> List[Any]:
    """
    Match user-provided layer names to available layers using fuzzy matching.

    Args:
        layers: List of layer objects with .name and .title attributes.
        target_names: List of names/titles to match.
        cutoff: Similarity threshold for fuzzy matching (0 to 1).

    Returns:
        A list of matched layer objects.
    """
    available_names = [layer.name for layer in layers]
    available_titles = [getattr(layer, "title", layer.name) for layer in layers]
    matched_layers: List[Any] = []
    unmatched: List[str] = []

    for name in target_names:
        # Try exact match first (case-insensitive)
        for layer in layers:
            if (
                layer.name.lower() == name.lower()
                or (getattr(layer, "title", "") or "").lower() == (name or "").lower()
            ):
                matched_layers.append(layer)
                break
        else:
            # Try fuzzy matching on names
            best_matches = difflib.get_close_matches(name, available_names, n=1, cutoff=cutoff)
            if best_matches:
                best_name = best_matches[0]
                matched_layer = next(layer for layer in layers if layer.name == best_name)
                matched_layers.append(matched_layer)
            else:
                # Try fuzzy matching on titles
                best_title_matches = difflib.get_close_matches(
                    name, available_titles, n=1, cutoff=cutoff
                )
                if best_title_matches:
                    best_title = best_title_matches[0]
                    matched_layer = next(
                        layer
                        for layer in layers
                        if getattr(layer, "title", layer.name) == best_title
                    )
                    matched_layers.append(matched_layer)
                else:
                    unmatched.append(name)

    return matched_layers
