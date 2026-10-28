import json
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools.base import InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel, Field
from typing_extensions import Annotated

from models.geodata import GeoDataObject
from models.states import GeoDataAgentState, get_medium_debug_state
from services.tools.utils import collect_stylable_layers, promote_layers_to_map


class PlanStep(BaseModel):
    """A single step in an execution plan."""

    action: str = Field(..., description="The natural-language description of what this step does")
    tool: str = Field(default="", description="The name of the tool that will be called")
    reason: str = Field(default="", description="Why this step is needed")


"""
 Utility tools to manage the GeoData State
"""


@tool
def set_result_list(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    results_title: str,
    result_tuples: list[list[str, str]],
) -> Union[Dict[str, Any], Command]:
    """Set results_title and append geodata_results, given a string and list of id and data_source_id tuples like: [['id1234','dataset1'],['id1235','dataset1']]"""
    update_dict: Dict[str, Any] = dict()
    if results_title is not None and results_title != "":
        update_dict["results_title"] = results_title
    if "result_list" in state:
        result_list = state["result_list"]
    else:
        result_list = []

    data_to_look_up: Set[Tuple[str, str]] = {
        tuple(result_tuple) for result_tuple in result_tuples or []
    }

    for geoobject in state["global_geodata"]:
        identifier: Tuple[str, str] = (geoobject.id, geoobject.data_source_id)

        if identifier in data_to_look_up:
            result_list.append(geoobject)
            data_to_look_up.remove(identifier)

    message: str
    if len(data_to_look_up) == 0:
        message = "Successfully added {len(result_tuples)} to the result list!"
    else:
        message = f"Added {len(result_tuples)-len(data_to_look_up)} geoobjects to the result list, but the following were not found in global_geodata: {json.dumps(list(data_to_look_up))} "

    return Command(
        update={
            "messages": [
                *state["messages"],
                ToolMessage(
                    name="set_result_list",
                    content=message,
                    tool_call_id=tool_call_id,
                ),
            ],
            "geodata_results": result_list,
        }
    )


@tool
def list_global_geodata(
    state: Annotated[GeoDataAgentState, InjectedState],
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    Lists the datasets in the global state
    """
    return [
        {
            "id": geodata.id,
            "data_source_id": geodata.data_source_id,
            "title": geodata.title,
        }
        for geodata in state["global_geodata"]
    ]


@tool
def list_user_layers(
    state: Annotated[GeoDataAgentState, InjectedState],
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """
    List all available layers: layers currently loaded on the map by the user
    (geodata_layers), analysis result layers created by tools (geodata_results),
    and results carried over from the previous turn (geodata_last_results).
    Use this when the user asks what datasets they have added, loaded, generated,
    are displaying on the map, or when you need to check whether a layer from an
    earlier turn is still available for processing.
    Returns a list of all loaded layers with their id, name, title, data_source, layer_type and data_link.
    When nothing is loaded the single returned entry says so explicitly: treat that
    as the final answer and stop, do not call this tool again.
    """
    layers = state.get("geodata_layers") or []
    result_layers = state.get("geodata_results") or []
    last_results = state.get("geodata_last_results") or []
    all_layers = (
        [(layer, "geodata_layers") for layer in layers]
        + [(layer, "geodata_results") for layer in result_layers]
        + [(layer, "geodata_last_results") for layer in last_results]
    )
    if not all_layers:
        # Returning a bare [] made the model retry this tool indefinitely; an
        # explicit terminal record states that the answer is final.
        return [
            {
                "status": "empty",
                "layer_count": 0,
                "message": (
                    "No layers are available: the map has no layers, and both "
                    "geodata_results and geodata_last_results are empty. "
                    "This is the final answer - do NOT call list_user_layers again. "
                    "Tell the user nothing is loaded and ask them to load or upload "
                    "data, or offer to fetch it."
                ),
            }
        ]

    result = []
    for layer, state_collection in all_layers:
        if isinstance(layer, dict):
            # Handle case where layer is a dictionary (e.g. during serialization/deserialization)
            result.append(
                {
                    "id": layer.get("id"),
                    "name": layer.get("name"),
                    "title": layer.get("title") or layer.get("name"),
                    "data_source": layer.get("data_source"),
                    "data_source_id": layer.get("data_source_id"),
                    "layer_type": layer.get("layer_type"),
                    "data_type": layer.get("data_type"),
                    "data_link": layer.get("data_link"),
                    "description": layer.get("description") or layer.get("llm_description") or "",
                    "state_collection": state_collection,
                    "is_result_layer": state_collection != "geodata_layers",
                }
            )
        else:
            # Handle case where layer is a Pydantic GeoDataObject
            result.append(
                {
                    "id": getattr(layer, "id", None),
                    "name": getattr(layer, "name", None),
                    "title": getattr(layer, "title", None) or getattr(layer, "name", None),
                    "data_source": getattr(layer, "data_source", None),
                    "data_source_id": getattr(layer, "data_source_id", None),
                    "layer_type": getattr(layer, "layer_type", None),
                    "data_type": getattr(layer, "data_type", None),
                    "data_link": getattr(layer, "data_link", None),
                    "description": getattr(layer, "description", None)
                    or getattr(layer, "llm_description", None)
                    or "",
                    "state_collection": state_collection,
                    "is_result_layer": state_collection != "geodata_layers",
                }
            )
    return result


@tool
def describe_geodata_object(
    state: Annotated[GeoDataAgentState, InjectedState],
    id: str,
    data_source_id: str,
) -> List[Dict[str, str]]:
    """
    Describes a GeoData Object with the given id and data_source_id returning its description and additional properties
    """
    found_object: List[GeoDataObject] = [
        geodata
        for geodata in state["global_geodata"]
        if geodata.id == id and geodata.data_source_id == data_source_id
    ]
    return found_object


@tool
def metadata_search(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    query: str,
    prioritize_layers: bool = True,
) -> Union[Dict[str, Any], Command]:
    """
    Search for a dataset by name/title in the geodata state and return its metadata.
    This tool is useful when a user asks for information about a specific dataset they've added to the map.

    Args:
        state: The agent state containing geodata_layers and geodata_last_results
        tool_call_id: ID for this tool call
        query: Search string to match against dataset titles or names
        prioritize_layers: If True, prioritize searching in geodata_layers (datasets added to map)

    Returns detailed metadata about matching datasets including description, source, type, etc.
    """
    # Get the datasets from state
    layers = state.get("geodata_layers") or []
    last_results = state.get("geodata_last_results") or []

    # Normalize query for better matching
    query_terms = query.lower().split()

    # Search function that assigns a relevance score to each dataset
    def get_relevance_score(dataset):
        score = 0
        title = (dataset.title or "").lower()
        name = (dataset.name or "").lower()

        # Exact match gets highest score
        if query.lower() in [title, name]:
            return 100

        # Partial matches
        for term in query_terms:
            if term in title:
                score += 10
            if term in name:
                score += 8
            if dataset.description and term in dataset.description.lower():
                score += 3
            if dataset.llm_description and term in dataset.llm_description.lower():
                score += 3
            if dataset.data_source and term in dataset.data_source.lower():
                score += 2

        return score

    # Search based on priority
    search_results = []

    if prioritize_layers:
        # First search in layers (datasets added to map)
        for dataset in layers:
            score = get_relevance_score(dataset)
            if score > 0:
                search_results.append((dataset, score, "layer"))

        # Then search in last results if needed
        if len(search_results) < 2:  # Only look in last_results if we don't have good matches yet
            for dataset in last_results:
                score = get_relevance_score(dataset)
                if score > 0:
                    search_results.append((dataset, score, "result"))
    else:
        # Search in both collections without prioritization
        for dataset in layers:
            score = get_relevance_score(dataset)
            if score > 0:
                search_results.append((dataset, score, "layer"))

        for dataset in last_results:
            score = get_relevance_score(dataset)
            if score > 0:
                search_results.append((dataset, score, "result"))

    # Sort by relevance
    search_results.sort(key=lambda x: x[1], reverse=True)

    # Format results for return
    if not search_results:
        return Command(
            update={
                "messages": [
                    *state["messages"],
                    ToolMessage(
                        name="metadata_search",
                        content=f"No datasets found matching '{query}'.",
                        tool_call_id=tool_call_id,
                    ),
                ]
            }
        )

    # Format the best match(es)
    best_matches = search_results[:2]  # Get top 2 matches
    response_parts = []

    for dataset, score, source in best_matches:
        # Build a structured response with all available metadata
        metadata = {
            "title": dataset.title or dataset.name,
            "name": dataset.name,
            "description": dataset.description or "No description available",
            "llm_description": dataset.llm_description,
            "data_source": dataset.data_source,
            "data_origin": dataset.data_origin,
            "layer_type": dataset.layer_type,
            "data_type": dataset.data_type,
            "bounding_box": dataset.bounding_box,
            "added_to_map": source == "layer",
        }

        # Filter out None values
        metadata = {k: v for k, v in metadata.items() if v is not None}
        response_parts.append(metadata)

    response_message = f"Found {len(best_matches)} dataset(s) matching '{query}':\n\n"
    response_message += json.dumps(response_parts, indent=2)

    return Command(
        update={
            "messages": [
                *state["messages"],
                ToolMessage(
                    name="metadata_search",
                    content=response_message,
                    tool_call_id=tool_call_id,
                ),
            ]
        }
    )


@tool
def create_execution_plan(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    title: str,
    steps: List[PlanStep],
    summary: str,
) -> Command:
    """
    为需要多步操作的复杂任务创建执行计划，展示给用户预览和确认。

    当用户请求需要连续调用 2 个或以上不同工具/操作时，必须先调用此工具列出计划，
    然后停止执行，等待用户确认。收到用户确认消息后，再按步骤顺序执行各工具。

    Args:
        title: 任务的简短标题（例如："缓冲区 + 叠加分析"）
        steps: 步骤列表，每项包含：
            - action (str): 该步骤的自然语言描述
            - tool (str): 将要调用的工具名称
            - reason (str, optional): 为什么需要这个步骤
        summary: 任务完成后预期效果的简要总结

    重要：调用此工具后，必须立即停止，不要继续调用其他工具。
    等待用户发送"确认"或类似消息后，再按步骤执行。
    """
    plan: Dict[str, Any] = {
        "title": title,
        "steps": [s.model_dump() if hasattr(s, "model_dump") else s for s in steps],
        "summary": summary,
        "status": "pending",
        "step_count": len(steps),
    }

    # Build a human-readable plan description for the tool message
    step_lines = []
    for i, step in enumerate(plan["steps"], 1):
        action = step.get("action", "")
        tool_name = step.get("tool", "")
        reason = step.get("reason", "")
        line = f"步骤 {i}：{action}"
        if tool_name:
            line += f"（工具：{tool_name}）"
        if reason:
            line += f"\n   原因：{reason}"
        step_lines.append(line)

    tool_message_content = (
        f"已创建执行计划：{title}\n\n" + "\n".join(step_lines) + f"\n\n预期结果：{summary}\n\n"
        "计划已发送给用户确认，请等待用户回复后再执行操作。"
    )

    return Command(
        update={
            "messages": [
                ToolMessage(
                    name="create_execution_plan",
                    content=tool_message_content,
                    tool_call_id=tool_call_id,
                )
            ],
            "execution_plan": plan,
        }
    )


@tool
def add_layers_to_map(
    state: Annotated[GeoDataAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    layer_names: Optional[List[str]] = None,
) -> Command:
    """
    Promote result layers onto the map (geodata_layers) so they become visible
    and stylable.

    Use this when tool output exists only in geodata_results / geodata_last_results
    and the user asks to add it to the map, display it, or continue with styling.
    Prefer calling this (or a styling tool that auto-promotes) instead of asking
    the user to click layers in the result list.

    Args:
        layer_names: Optional names/titles to promote. If omitted, promotes all
            layers found in geodata_results and geodata_last_results that are not
            already on the map. When the map already has layers and names are
            omitted, still promotes unmatched result layers.
    """
    if layer_names:
        targets = collect_stylable_layers(state, layer_names)
    else:
        # Promote result collections that are not already on the map.
        map_ids = {getattr(layer, "id", None) for layer in (state.get("geodata_layers") or [])}
        targets = [
            layer
            for layer in collect_stylable_layers(state)
            if getattr(layer, "id", None) not in map_ids
        ]

    if not targets:
        message = (
            "No result layers found to add to the map. "
            "geodata_results / geodata_last_results are empty or already on the map."
        )
        return Command(
            update={
                "messages": [
                    *state["messages"],
                    ToolMessage(
                        name="add_layers_to_map",
                        content=message,
                        tool_call_id=tool_call_id,
                    ),
                ]
            }
        )

    update = promote_layers_to_map(state, targets)
    names = ", ".join(
        getattr(layer, "title", None) or getattr(layer, "name", "") for layer in targets
    )
    update["messages"] = [
        *state["messages"],
        ToolMessage(
            name="add_layers_to_map",
            content=f"Added {len(targets)} layer(s) to the map: {names}",
            tool_call_id=tool_call_id,
        ),
    ]
    return Command(update=update)


if __name__ == "__main__":
    initial_geo_state: GeoDataAgentState = get_medium_debug_state(True)

    print(
        set_result_list.run(
            state=initial_geo_state,
            tool_input={
                "state": initial_geo_state,
                "tool_call_id": "testcallid1234",
                "results_title": "Results:",
                "result_tuples": [("1512", "db_name")],
            },
        )
    )
