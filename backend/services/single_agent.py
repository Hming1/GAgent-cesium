import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent

from models.settings_model import ModelSettings, ToolConfig
from models.states import GeoDataAgentState, get_minimal_debug_state
from services.ai.llm_config import get_llm
from services.agent_skills import build_layer_keywords, build_plan_tool_aliases
from services.conversation_manager import ConversationManager
from services.default_agent_settings import DEFAULT_AVAILABLE_TOOLS, DEFAULT_SYSTEM_PROMPT
from services.tools.geostate_management import describe_geodata_object
from utility.tool_configurator import create_configured_tools

logger = logging.getLogger(__name__)

# Module-level conversation managers (per session)
# Format: {session_id: {"manager": ConversationManager, "last_access": timestamp}}
conversation_managers: Dict[str, Dict[str, Any]] = {}

# Session TTL in seconds (default: 1 hour)
SESSION_TTL = 3600


_PLAN_TOOL_ALIASES = build_plan_tool_aliases()
_LAYER_KEYWORDS = build_layer_keywords()


def _normalize_plan_tool_name(tool_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", tool_name.strip().lower()).strip("_")


def _tool_name_variants(tool_name: Any) -> Set[str]:
    raw_tool_name = str(tool_name or "").strip()
    if not raw_tool_name:
        return set()

    normalized = _normalize_plan_tool_name(raw_tool_name)
    variants = {raw_tool_name, raw_tool_name.lower(), normalized}
    alias = _PLAN_TOOL_ALIASES.get(normalized)
    if alias:
        variants.add(alias)
    return {variant for variant in variants if variant}


def _planned_tool_keys(plan_tools: Optional[List[str]]) -> Set[str]:
    keys: Set[str] = set()
    for raw_tool in plan_tools or []:
        keys.update(_tool_name_variants(raw_tool))
    return keys


def _filter_tools_for_confirmed_plan(
    tools_dict: Dict[str, BaseTool],
    plan_tools: Optional[List[str]],
) -> Dict[str, BaseTool]:
    planned_keys = _planned_tool_keys(plan_tools)
    if not planned_keys:
        return tools_dict

    filtered = {}
    for key, tool in tools_dict.items():
        tool_keys = _tool_name_variants(key) | _tool_name_variants(getattr(tool, "name", key))
        if tool_keys & planned_keys:
            filtered[key] = tool
    return filtered or tools_dict


def prune_messages(
    messages: List[BaseMessage], window_size: int, preserve_system: bool = True
) -> List[BaseMessage]:
    """Prune message history to keep only recent messages.

    Args:
        messages: List of messages to prune
        window_size: Maximum number of recent messages to keep (excluding system messages)
        preserve_system: If True, always keep the first system message (default: True)

    Returns:
        Pruned list of messages

    Examples:
        >>> messages = [SystemMessage("..."), HumanMessage("1"), AIMessage("2"), ...]
        >>> prune_messages(messages, window_size=5)  # Keeps system + last 5 messages
    """
    if not messages or window_size <= 0:
        return messages

    # Separate system messages from conversation messages（分离系统对话和普通对话）
    system_messages = []
    conversation_messages = []

    for msg in messages:
        if preserve_system and isinstance(msg, SystemMessage):
            system_messages.append(msg)
        else:
            conversation_messages.append(msg)

    # Keep only the most recent window_size messages from conversation
    pruned_conversation = conversation_messages[-window_size:] if conversation_messages else []

    # Combine: system messages first, then recent conversation
    result = system_messages + pruned_conversation

    if len(conversation_messages) > window_size:
        logger.info(
            f"Pruned message history: {len(conversation_messages)} -> {len(pruned_conversation)} "
            f"messages (kept {len(system_messages)} system messages)"
        )

    return result


def _get_message_management_mode(settings_mode: Optional[str] = None) -> str:
    """Get the message management mode from settings or environment.

    Returns the configured message management strategy:
    - 'summarize' (default): Use LLM-based conversation summarization.
      Older messages are intelligently summarized to preserve context
      while reducing token usage.
    - 'prune': Use simple window-based truncation.
      Only the most recent messages are kept; older messages are discarded.

    Priority order:
    1. User/organization settings (settings_mode parameter)
    2. MESSAGE_MANAGEMENT_MODE environment variable
    3. Default: 'summarize'

    Args:
        settings_mode: Optional mode from user/organization settings

    Returns:
        One of 'summarize' or 'prune'
    """
    import os

    # Check user/organization settings first
    if settings_mode:
        mode = settings_mode.lower().strip()
        if mode in ("summarize", "prune"):
            return mode
        logger.warning(
            f"Invalid message_management_mode='{mode}' in settings, "
            f"checking environment variable. Valid values: 'summarize', 'prune'"
        )

    # Fallback to environment variable
    mode = os.getenv("MESSAGE_MANAGEMENT_MODE", "summarize").lower().strip()
    if mode not in ("summarize", "prune"):
        logger.warning(
            f"Unknown MESSAGE_MANAGEMENT_MODE='{mode}', falling back to 'summarize'. "
            f"Valid values: 'summarize', 'prune'"
        )
        return "summarize"
    return mode


async def prepare_messages(
    messages: List[BaseMessage],
    message_window_size: int,
    session_id: Optional[str] = None,
    llm: Optional[Any] = None,
    settings_mode: Optional[str] = None,
) -> List[BaseMessage]:
    """Prepare messages using the configured message management strategy.

    Applies either LLM-based summarization or simple window pruning based on:
    1. User/organization settings (settings_mode parameter)
    2. MESSAGE_MANAGEMENT_MODE environment variable
    3. Default: 'summarize'

    Args:
        messages: Full message history to process
        message_window_size: Window size for recent messages
        session_id: Session ID for conversation tracking (required for summarization)
        llm: Language model instance for summarization (optional, falls back to pruning)
        settings_mode: Optional mode from user/organization settings

    Returns:
        Processed message list, either summarized or pruned
    """
    mode = _get_message_management_mode(settings_mode)

    if mode == "summarize" and session_id:
        manager = get_conversation_manager(session_id, message_window_size)
        try:
            result = await manager.process_messages(messages, llm=llm)
            logger.info(
                f"Message summarization: {len(messages)} -> {len(result)} messages "
                f"(session: {session_id})"
            )
            return result
        except Exception as e:
            logger.error(f"Summarization failed, falling back to pruning: {e}")
            return prune_messages(messages, window_size=message_window_size)
    elif mode == "summarize" and not session_id:
        logger.warning("Summarization mode requires session_id, falling back to pruning")
        return prune_messages(messages, window_size=message_window_size)
    else:
        # mode == "prune"
        return prune_messages(messages, window_size=message_window_size)


def _cleanup_expired_sessions():
    """Clean up expired conversation manager sessions.

    Removes sessions that haven't been accessed within SESSION_TTL.
    Called periodically to prevent memory leaks.
    """
    current_time = time.time()
    expired_sessions = []

    for session_id, session_data in conversation_managers.items():
        last_access = session_data.get("last_access", 0)
        if current_time - last_access > SESSION_TTL:
            expired_sessions.append(session_id)

    for session_id in expired_sessions:
        del conversation_managers[session_id]
        logger.info(f"Cleaned up expired conversation session: {session_id}")

    if expired_sessions:
        logger.info(f"Cleaned up {len(expired_sessions)} expired conversation sessions")


def get_conversation_manager(session_id: str, message_window_size: int) -> ConversationManager:
    """Get or create conversation manager for a session.

    Args:
        session_id: Unique session identifier
        message_window_size: Window size for recent messages

    Returns:
        ConversationManager instance for this session
    """
    # Clean up expired sessions periodically
    _cleanup_expired_sessions()

    current_time = time.time()

    if session_id not in conversation_managers:
        # Create new conversation manager
        manager = ConversationManager(
            max_messages=message_window_size * 2,
            summarize_threshold=message_window_size + 5,
            summary_window=message_window_size,
        )
        conversation_managers[session_id] = {"manager": manager, "last_access": current_time}
        logger.info(f"Created new conversation manager for session: {session_id}")
    else:
        # Update last access time
        conversation_managers[session_id]["last_access"] = current_time

    return conversation_managers[session_id]["manager"]


async def create_geo_agent(
    model_settings: Optional[ModelSettings] = None,
    selected_tools: Optional[List[ToolConfig]] = None,
    enable_parallel_tools: bool = False,
    query: Optional[str] = None,
    session_id: Optional[str] = None,
    mcp_servers: Optional[List] = None,  # List of MCPServer objects
    suppress_plan_tool: bool = False,
    confirmed_plan_tools: Optional[List[str]] = None,
) -> Tuple[CompiledStateGraph, Any]:
    """Create a geo agent with specified model and tools.

    Args:
        model_settings: Model configuration (provider, name, max_tokens, system_prompt)
        selected_tools: Tool configurations to enable/disable
        enable_parallel_tools: Whether to enable parallel tool execution
            (default: False, experimental)
        query: Current user query for dynamic tool selection (optional)
        session_id: Unique session identifier for conversation tracking
            (used for conversation summarization)
        mcp_servers: List of MCPServer objects to load external tools from
            (optional, supports authentication via api_key and headers fields)

    Returns:
        Tuple of (CompiledStateGraph, llm) - the agent graph and the LLM instance.
        The LLM is returned so callers can pass it to prepare_messages() for
        conversation summarization.

    Note:
        Parallel tool execution is currently EXPERIMENTAL. While it can speed up multi-tool queries,
        it may cause state corruption if multiple tools modify the same state fields concurrently.
        Use with caution and monitor for race conditions.

        Dynamic tool selection uses semantic similarity to select relevant tools based on
        the query, supporting all languages. This reduces context size and improves performance.

        Message management is controlled by the MESSAGE_MANAGEMENT_MODE environment variable.
        Use prepare_messages() before invoking the agent to handle message history.

        MCP server integration allows loading external tools from Model Context Protocol
        servers, enabling GeoAgent to use third-party tools seamlessly.
    """

    # Use model_settings if provided, otherwise use env defaults
    if model_settings is not None:
        from services.ai.llm_config import get_llm_for_provider

        llm, model_capabilities = get_llm_for_provider(
            provider_name=model_settings.model_provider,
            max_tokens=model_settings.max_tokens,
            model_name=model_settings.model_name,
        )
        system_prompt = (
            model_settings.system_prompt if model_settings.system_prompt else DEFAULT_SYSTEM_PROMPT
        )
        if getattr(model_settings, "plan_mode", False) and not suppress_plan_tool:
            system_prompt += (
                "\n\n## PLAN MODE (STRICT ENABLED) / \u8ba1\u5212\u6a21\u5f0f\n"
                "\n"
                "\u5f53\u7528\u6237\u63d0\u51fa\u65b0\u8bf7\u6c42\u65f6\uff0c"
                "\u4f60\u5fc5\u987b\u8c03\u7528 create_execution_plan \u5de5\u5177"
                "\uff08\u51fd\u6570\u8c03\u7528\uff09\u6765\u751f\u6210\u6267\u884c"
                "\u8ba1\u5212\uff0c\u800c\u4e0d\u662f\u628a\u8ba1\u5212\u5199\u6210"
                "\u6587\u672c\u3002\n"
                "\n"
                "Rules:\n"
                "1. For any NEW user request, you MUST CALL the create_execution_plan "
                "tool (function call) FIRST. Do NOT write the plan as text.\n"
                "2. After calling create_execution_plan, STOP immediately. Do not call "
                "any other tool. Wait for the user to confirm or cancel.\n"
                "3. If the user confirms, DO NOT call create_execution_plan again. "
                "Execute the plan step-by-step using the planned tools.\n"
                "\n"
                "Tool parameters for create_execution_plan:\n"
                "- title (str): Short title of the task\n"
                "- steps (list): List of step objects, each with:\n"
                "    - action (str): What this step does\n"
                "    - tool (str): Name of the tool to call\n"
                "    - reason (str): Why this step is needed\n"
                "- summary (str): Expected outcome after completion\n"
            )
    else:
        # Fall back to env-configured provider
        llm = get_llm()
        # No capabilities available for default LLM
        from services.ai.llm_config import ModelCapabilities

        model_capabilities = ModelCapabilities()
        system_prompt = DEFAULT_SYSTEM_PROMPT

    tools_dict: Dict[str, BaseTool] = create_configured_tools(
        DEFAULT_AVAILABLE_TOOLS, selected_tools or []
    )
    # Create a shallow copy to avoid mutating the global DEFAULT_AVAILABLE_TOOLS
    tools_dict = dict(tools_dict)

    # Remove create_execution_plan if plan_mode is disabled or this invocation is
    # executing an already-confirmed plan.
    plan_mode_enabled = getattr(model_settings, "plan_mode", False) if model_settings else False
    if (not plan_mode_enabled or suppress_plan_tool) and "create_execution_plan" in tools_dict:
        del tools_dict["create_execution_plan"]
    if suppress_plan_tool:
        before_count = len(tools_dict)
        tools_dict = _filter_tools_for_confirmed_plan(tools_dict, confirmed_plan_tools)
        logger.info(
            "Confirmed plan tool filter: %s/%s tools available",
            len(tools_dict),
            before_count,
        )
    # Apply dynamic tool selection if enabled
    enable_dynamic_tools = (
        model_settings.enable_dynamic_tools
        if model_settings and hasattr(model_settings, "enable_dynamic_tools")
        else False
    )

    if enable_dynamic_tools and query:
        from services.tool_selector import create_tool_selector

        # Get embeddings from LLM if available
        embeddings = None
        if hasattr(llm, "embeddings"):
            embeddings = llm.embeddings
        else:
            # Try to create embeddings from same provider
            try:
                from services.ai.llm_config import get_embeddings

                embeddings = get_embeddings()
            except Exception as e:
                logger.warning(f"Could not load embeddings for dynamic tool selection: {e}")

        # Create tool selector with settings
        selector = create_tool_selector(
            embeddings=embeddings,
            strategy=(
                model_settings.tool_selection_strategy
                if hasattr(model_settings, "tool_selection_strategy")
                else "conservative"
            ),
            similarity_threshold=(
                model_settings.tool_similarity_threshold
                if hasattr(model_settings, "tool_similarity_threshold")
                else 0.3
            ),
            max_tools=(
                model_settings.max_tools_per_query
                if hasattr(model_settings, "max_tools_per_query")
                else None
            ),
        )

        # Select relevant tools
        tools: List[BaseTool] = await selector.select_tools(query, tools_dict)
        logger.info(f"Dynamic tool selection: {len(tools)}/{len(tools_dict)} tools selected")
    else:
        tools: List[BaseTool] = list(tools_dict.values())

    # Load external MCP tools if configured
    if mcp_servers:
        try:
            from services.mcp.integration import load_mcp_tools

            for mcp_server in mcp_servers:
                try:
                    server_url = mcp_server.url
                    api_key = getattr(mcp_server, "api_key", None)
                    headers = getattr(mcp_server, "headers", None)

                    logger.info(f"Loading tools from MCP server: {server_url}")
                    mcp_tools = await load_mcp_tools(server_url, api_key=api_key, headers=headers)
                    tools.extend(mcp_tools)
                    logger.info(f"Loaded {len(mcp_tools)} tools from MCP server: {server_url}")
                except Exception as e:
                    logger.error(f"Failed to load tools from MCP server {mcp_server.url}: {e}")
                    # Continue with other servers even if one fails
        except Exception as e:
            logger.error(f"Failed to import MCP integration: {e}")

    # Enable langgraph debug logging when global log level is DEBUG
    debug_enabled = logger.isEnabledFor(logging.DEBUG)

    planning_only = plan_mode_enabled and not suppress_plan_tool
    if planning_only:
        # History can contain earlier tool calls and confirmations. Enforce the
        # current request's planning phase in the graph, not just in the prompt.
        # Preserve the business-tool catalog for planning, including MCP tools,
        # but do not make any of those operations executable before confirmation.
        catalog = "\n".join(
            f"- {item.name}: {item.description}"
            for item in tools
            if item.name != "create_execution_plan"
        )
        system_prompt += (
            "\n\nCURRENT REQUEST: planning only; not yet approved. Previous conversation "
            "confirmations apply only to their earlier tasks. Create a NEW plan for the "
            "latest request and wait for confirmation.\n"
            "Available tools to reference in plan steps (not callable in this phase):\n" + catalog
        )
        # Always restore the planner if dynamic selection or tool preferences
        # omitted it. Copy it so return_direct does not mutate the global registry.
        tools = [
            DEFAULT_AVAILABLE_TOOLS["create_execution_plan"].model_copy(
                update={"return_direct": True}
            )
        ]

    # Determine if parallel tool calling should be enabled
    # State reducers now handle concurrent updates safely
    parallel_tool_calls = False
    if enable_parallel_tools and not planning_only:
        # Check if model supports parallel tool calls
        if model_settings:
            parallel_tool_calls = model_capabilities.supports_parallel_tool_calls

            if parallel_tool_calls:
                logger.info(
                    "Parallel tool execution ENABLED. "
                    "State reducers will handle concurrent updates."
                )
        else:
            logger.warning(
                "enable_parallel_tools=True but no model_settings provided, "
                "falling back to sequential execution"
            )

    def _query_mentions_layers(state: GeoDataAgentState) -> bool:
        """Check if the latest user message is related to layer/data operations."""
        messages = state.get("messages", [])
        if not messages:
            return False
        # Find the latest human message
        for msg in reversed(messages):
            if getattr(msg, "type", None) == "human" or (
                isinstance(msg, dict) and msg.get("type") == "human"
            ):
                content = (
                    getattr(msg, "content", "")
                    if not isinstance(msg, dict)
                    else msg.get("content", "")
                )
                query_lower = str(content).lower()
                return any(kw in query_lower for kw in _LAYER_KEYWORDS)
        return False

    # def prompt_modifier(state: GeoDataAgentState) -> str:
    #     """Inject loaded layer info only when the user's query is layer-related."""
    #     layers = state.get("geodata_layers", [])
    #     if not layers or not _query_mentions_layers(state):
    #         return system_prompt

    #     layer_lines = []
    #     for layer in layers:
    #         name = getattr(layer, "name", None) or "Unknown"
    #         title = getattr(layer, "title", None) or name
    #         layer_id = getattr(layer, "id", "?")
    #         data_link = getattr(layer, "data_link", "")
    #         layer_lines.append(f"  - {title} (id={layer_id}, link={data_link})")

    #     layer_block = (
    #         "\n\n<system_state>\n"
    #         f"Currently {len(layers)} layer(s) loaded on the map:\n"
    #         + "\n".join(layer_lines)
    #         + "\n</system_state>"
    #     )
    #     return system_prompt + layer_block

    def prompt_modifier(state: GeoDataAgentState) -> list:
        """Inject currently loaded layer info into system prompt on every invocation.

        Always injects a <system_state> block so the LLM knows what layers are
        loaded and can directly answer questions like '我加载了什么图层'.
        """
        from langchain_core.messages import SystemMessage as LCSystemMessage

        layers = state.get("geodata_layers") or []
        result_layers = state.get("geodata_results") or []
        last_results = state.get("geodata_last_results") or []
        execution_plan = state.get("execution_plan")
        messages = state.get("messages", [])

        # Build system state block
        state_parts = []

        if layers:
            layer_lines = []
            for layer in layers:
                name = getattr(layer, "name", None) or "Unknown"
                title = getattr(layer, "title", None) or name
                layer_id = getattr(layer, "id", "?")
                data_source = getattr(layer, "data_source", "") or ""
                layer_type = getattr(layer, "layer_type", "") or ""
                data_link = getattr(layer, "data_link", "") or ""
                description = (
                    getattr(layer, "llm_description", "") or getattr(layer, "description", "") or ""
                )
                desc_snippet = (
                    (description[:120] + "...") if len(description) > 120 else description
                )

                info = f"  - [{layer_id}] {title}"
                if data_source:
                    info += f" | source: {data_source}"
                if layer_type:
                    info += f" | type: {layer_type}"
                if data_link:
                    info += f" | link: {data_link}"
                if desc_snippet:
                    info += f"\n      Description: {desc_snippet}"
                layer_lines.append(info)

            state_parts.append(
                f"Currently {len(layers)} layer(s) loaded on the map (geodata_layers):\n"
                + "\n".join(layer_lines)
            )
        else:
            state_parts.append("geodata_layers: (none - no layers currently loaded on the map)")

        if result_layers:
            result_layer_lines = []
            for item in result_layers[:8]:
                name = getattr(item, "name", None) or "Unknown"
                title = getattr(item, "title", None) or name
                item_id = getattr(item, "id", "?")
                data_source_id = getattr(item, "data_source_id", "") or ""
                data_link = getattr(item, "data_link", "") or ""
                info = f"  - [{item_id}] {title} | name: {name}"
                if data_source_id:
                    info += f" | data_source_id: {data_source_id}"
                if data_link:
                    info += f" | link: {data_link}"
                result_layer_lines.append(info)
            state_parts.append(
                "Generated analysis result layers (geodata_results, use these directly; "
                "do not search metadata for these IDs):\n" + "\n".join(result_layer_lines)
            )

        if last_results:
            result_lines = []
            for item in last_results[:5]:  # Show up to 5 recent results
                name = getattr(item, "name", None) or "Unknown"
                title = getattr(item, "title", None) or name
                item_id = getattr(item, "id", "?")
                result_lines.append(f"  - [{item_id}] {title}")
            state_parts.append(
                "Recent tool results (geodata_last_results, up to 5):\n" + "\n".join(result_lines)
            )

        if execution_plan:
            plan_title = execution_plan.get("title", "Untitled plan")
            plan_summary = execution_plan.get("summary", "")
            plan_status = execution_plan.get("status", "pending")
            plan_steps = execution_plan.get("steps") or []
            step_lines = []
            for i, step in enumerate(plan_steps, 1):
                action = step.get("action", "")
                tool_name = step.get("tool", "")
                line = f"  {i}. {action}"
                if tool_name:
                    line += f" | tool: {tool_name}"
                step_lines.append(line)

            plan_block = (
                f"execution_plan: {plan_title}\n"
                f"status: {plan_status}\n"
                f"summary: {plan_summary}\n" + "\n".join(step_lines)
            )
            if plan_status == "confirmed":
                plan_block += (
                    "\nThe user confirmed this plan. Execute only the listed planned "
                    "steps using the available business tools. Do not create another "
                    "execution plan. Do not call metadata_search or other discovery "
                    "tools unless they are explicitly listed in the plan. When the "
                    "planned steps have produced enough results, stop tool use and "
                    "write the final answer."
                )
            state_parts.append(plan_block)

        state_block = "\n\n<system_state>\n" + "\n\n".join(state_parts) + "\n</system_state>"

        full_prompt = system_prompt + state_block

        # Safety: filter out any HumanMessage with empty content.
        # Some LLM APIs (e.g. Moonshot) reject empty user messages with 400.
        sanitized = []
        system_contents = [full_prompt]
        for msg in messages:
            # Qwen permits exactly one system message at index zero. Summaries
            # and memory are also SystemMessages, so merge their content here.
            if isinstance(msg, SystemMessage):
                system_contents.append(msg.content)
                continue
            if isinstance(msg, HumanMessage) and not str(getattr(msg, "content", "") or "").strip():
                logger.warning("prompt_modifier: dropping HumanMessage with empty content")
                continue
            sanitized.append(msg)

        if all(isinstance(content, str) for content in system_contents):
            combined_content = "\n\n".join(system_contents)
        else:
            combined_content = []
            for content in system_contents:
                combined_content.extend(
                    content if isinstance(content, list) else [{"type": "text", "text": content}]
                )
        return [LCSystemMessage(content=combined_content)] + sanitized

    binding_options = {"parallel_tool_calls": parallel_tool_calls}
    if planning_only:
        binding_options["tool_choice"] = "create_execution_plan"

    agent = create_react_agent(
        name="GeoAgent",
        state_schema=GeoDataAgentState,
        tools=tools,
        model=llm.bind_tools(tools, **binding_options),
        prompt=prompt_modifier,
        debug=debug_enabled,
        # config_schema=GeoData,
        # response_format=GeoData
    )
    return agent, llm


if __name__ == "__main__":
    import asyncio

    # Initialize geodata state (e.g. Berlin) with both public and private data

    debug_tool: bool = False
    initial_geo_state: GeoDataAgentState = get_minimal_debug_state(debug_tool)
    single_agent, _llm = asyncio.run(create_geo_agent())

    if not debug_tool:
        # Ask the agent; private fields are kept internally but not sent to the LLM
        response = single_agent.invoke(initial_geo_state)
        print(64 * "-")
        print(response["messages"])
        for message in response["messages"]:
            print(message.type, ":", message.content)
        print(64 * "-")
        print(response["geodata_results"])
        # print("-"*64)
        # print(response["messages"])
    else:
        # Tool debugging
        print(
            describe_geodata_object.run(
                state=initial_geo_state,
                tool_input={
                    "state": initial_geo_state,
                    "id": "1512",
                    "data_source_id": "db_name",
                },
            )
        )
