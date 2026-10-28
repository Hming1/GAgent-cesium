import asyncio
import json
import logging
import os
import re
import uuid
from contextlib import suppress
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_session
from models.geodata import GeoDataObject, mock_geodata_objects
from models.messages.chat_messages import GeoAgentRequest, GeoAgentResponse
from models.settings_model import SettingsSnapshot
from models.states import DataState, GeoDataAgentState
from services.agent_trace import build_agent_run_config

# Lazy imports for heavy modules (loaded only when chat endpoint is called)
# from services.multi_agent_orch import multi_agent_executor
# from services.single_agent import create_geo_agent
# import openai

logger = logging.getLogger(__name__)

# Shared agent step budget for both /chat and /chat/stream. Multi-step geo tasks
# (discover -> load -> filter -> geoprocess -> style) routinely need more than the
# LangGraph default of 25 node visits.
AGENT_RECURSION_LIMIT = int(os.getenv("AGENT_RECURSION_LIMIT", "200"))

# Global dict to track cancellation requests by session_id
_cancellation_flags: Dict[str, bool] = {}
_cancellation_lock = asyncio.Lock()


async def _persist_conversation_turn(
    *,
    db: Optional[AsyncSession] = None,
    options: Any,
    session_id: Optional[str],
    user_id: Any,
    query: Optional[str],
    result_messages: Any,
    geodata_layers: Any = None,
    run_id: Any = None,
) -> None:
    """Best-effort chat history persistence for evaluation and restore.

    Always opens a fresh DB session. The request-scoped ``db`` from
    ``Depends(get_session)`` is unsafe for ``/chat/stream``: FastAPI may close
    it when the StreamingResponse starts, so writes would silently no-op.
    """
    try:
        from db.session import AsyncSessionLocal
        from services.conversation.store import (
            ConversationStore,
            build_layer_attachments,
        )

        if AsyncSessionLocal is None:
            logger.warning(
                "Skip conversation persist: DATABASE_URL not configured "
                "(AsyncSessionLocal is None)"
            )
            return

        conversation_id = getattr(options, "conversation_id", None) or session_id
        if not conversation_id:
            logger.warning("Skip conversation persist: missing conversation_id and session_id")
            return

        async with AsyncSessionLocal() as persist_db:
            store = ConversationStore(persist_db)
            await store.record_turn(
                conversation_id=str(conversation_id),
                user_id=user_id,
                session_id=session_id,
                query=query,
                result_messages=result_messages,
                run_id=run_id,
                attachments=build_layer_attachments(geodata_layers),
                include_tool_messages=True,
            )
            logger.info(
                "Persisted conversation turn conversation_id=%s run_id=%s",
                conversation_id,
                run_id,
            )
    except Exception as exc:
        logger.warning("Failed to persist conversation turn: %s", exc, exc_info=True)


# Keep SSE/result and conversation history payloads browser-safe. Full tool
# text stays in the live LangGraph state for the current turn; only the
# client/DB copy is truncated.
_CLIENT_TOOL_CONTENT_MAX = 4_000


def _truncate_client_text(value: Any, max_chars: int = _CLIENT_TOOL_CONTENT_MAX) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= max_chars:
        return value
    return (
        f"{value[:max_chars]}\n" f"...[truncated {len(value) - max_chars} chars for client/history]"
    )


def _truncate_tool_calls_for_client(tool_calls: Any) -> Any:
    """Drop bulky sandbox `code` args from AI tool_calls sent to the browser."""
    if not isinstance(tool_calls, list):
        return tool_calls
    trimmed = []
    for call in tool_calls:
        if not isinstance(call, dict):
            trimmed.append(call)
            continue
        item = dict(call)
        args = item.get("args")
        if isinstance(args, dict) and isinstance(args.get("code"), str):
            code = args["code"]
            item["args"] = {
                **args,
                "code": _truncate_client_text(code, 600),
                "code_chars": len(code),
            }
        trimmed.append(item)
    return trimmed


def make_json_serializable(obj: Any, *, for_client: bool = False) -> Any:
    """
    Recursively convert non-JSON-serializable objects to JSON-serializable format.
    Handles LangChain message objects, lists, dicts, and other common types.

    When ``for_client`` is True, oversized tool message bodies are truncated so
    SSE ``result`` events and conversation restores do not freeze the browser.
    """
    if obj is None:
        return None

    # Handle LangChain message objects
    if isinstance(obj, HumanMessage):
        return {"type": "human", "content": obj.content}
    elif isinstance(obj, AIMessage):
        res = {"type": "ai", "content": obj.content}
        if getattr(obj, "additional_kwargs", None):
            res["additional_kwargs"] = make_json_serializable(
                obj.additional_kwargs, for_client=for_client
            )
        if getattr(obj, "tool_calls", None):
            tool_calls = make_json_serializable(obj.tool_calls, for_client=for_client)
            if for_client:
                tool_calls = _truncate_tool_calls_for_client(tool_calls)
            res["tool_calls"] = tool_calls
        return res
    elif isinstance(obj, SystemMessage):
        return {"type": "system", "content": obj.content}
    elif isinstance(obj, (ToolMessage, FunctionMessage)):
        content = obj.content
        if for_client:
            content = _truncate_client_text(content)
        res = {"type": "tool", "content": content}
        if getattr(obj, "tool_call_id", None):
            res["tool_call_id"] = obj.tool_call_id
        if getattr(obj, "name", None):
            res["name"] = obj.name
        if getattr(obj, "status", None):
            res["status"] = obj.status
        return res
    elif isinstance(obj, BaseMessage):
        return {"type": "message", "content": str(obj.content)}

    # Handle lists
    elif isinstance(obj, list):
        return [make_json_serializable(item, for_client=for_client) for item in obj]

    # Handle dicts
    elif isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for key, value in list(obj.items()):
            # Truncate nested tool content fields when shipping to the browser.
            if for_client and key in {"content", "output_preview"} and isinstance(value, str):
                out[key] = _truncate_client_text(value)
            else:
                out[key] = make_json_serializable(value, for_client=for_client)
        return out

    # Handle primitive types and other JSON-serializable objects
    elif isinstance(obj, (str, int, float, bool)):
        return obj

    # For everything else, convert to string
    else:
        try:
            # Try to serialize it first
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            # If it fails, convert to string
            return str(obj)


def _extract_tool_call_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "tool_call_id"):
        return getattr(value, "tool_call_id", None)
    if isinstance(value, dict):
        for key in ("tool_call_id", "id"):
            found = value.get(key)
            if isinstance(found, str) and found:
                return found
        args = value.get("args")
        if isinstance(args, dict):
            found = _extract_tool_call_id(args)
            if found:
                return found
        messages = value.get("messages")
        if isinstance(messages, list):
            for message in messages:
                found = _extract_tool_call_id(message)
                if found:
                    return found
    if isinstance(value, list):
        for item in value:
            found = _extract_tool_call_id(item)
            if found:
                return found
    return None


def _first_tool_message(value: Any) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    if isinstance(value, (ToolMessage, FunctionMessage)):
        return make_json_serializable(value)
    if isinstance(value, dict):
        if value.get("type") == "tool" or value.get("tool_call_id"):
            return make_json_serializable(value)
        messages = value.get("messages")
        if isinstance(messages, list):
            for message in messages:
                found = _first_tool_message(message)
                if found:
                    return found
        update = value.get("update")
        if isinstance(update, dict):
            found = _first_tool_message(update)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _first_tool_message(item)
            if found:
                return found
    return None


def _tool_status_from_message(message: Optional[Dict[str, Any]]) -> str:
    if not message:
        return "success"
    status = message.get("status")
    if status:
        return str(status)
    content = str(message.get("content") or "")
    if content.lower().startswith("error") or "status='error'" in content:
        return "error"
    return "success"


def _build_tool_output_data(
    tool_name: str,
    raw_output: Any,
    *,
    tool_call_id: Optional[str] = None,
    output_type: Optional[str] = None,
) -> Dict[str, Any]:
    serializable_output = make_json_serializable(raw_output)
    tool_message = _first_tool_message(serializable_output)
    status = _tool_status_from_message(tool_message)
    if status == "error":
        status = "failed"
    content = str(tool_message.get("content") or "") if tool_message else ""
    resolved_tool_call_id = tool_call_id or _extract_tool_call_id(serializable_output)
    is_state_update = isinstance(serializable_output, dict) and (
        "messages" in serializable_output
        or "geodata_results" in serializable_output
        or "geodata_layers" in serializable_output
    )

    if tool_message:
        preview = content[:200] + ("..." if len(content) > 200 else "")
    elif is_state_update:
        msg_count = len(serializable_output.get("messages", []))
        preview = f"State update with {msg_count} messages"
    else:
        output_str = str(serializable_output)
        preview = output_str[:200] + ("..." if len(output_str) > 200 else "")

    # Never push multi-MB tool bodies on the SSE wire — preview is enough for UI.
    safe_error = _truncate_client_text(content, 2_000) if status == "failed" else None
    output_data = {
        "tool": tool_name,
        "tool_call_id": resolved_tool_call_id,
        "status": status,
        "output_preview": preview,
        "error_message": safe_error,
        "is_state_update": is_state_update,
        "output_type": output_type
        or ("state" if is_state_update else type(serializable_output).__name__),
    }
    if tool_message:
        trimmed = dict(tool_message)
        trimmed["content"] = _truncate_client_text(tool_message.get("content"))
        output_data["tool_message"] = trimmed
    elif not is_state_update:
        output_data["output"] = make_json_serializable(serializable_output, for_client=True)
    return output_data


def _ensure_tool_call_id(tool_name: str, tool_call_id: Optional[str], fallback_id: Any) -> str:
    if tool_call_id:
        return tool_call_id
    if fallback_id:
        return str(fallback_id)
    return f"tool-{tool_name}-{uuid.uuid4().hex}"


def _tool_event_key(tool_name: str, tool_call_id: Optional[str], fallback_id: Any) -> str:
    return _ensure_tool_call_id(tool_name, tool_call_id, fallback_id)


def normalize_messages(raw: Optional[List[BaseMessage]]) -> List[BaseMessage]:
    if raw is None:
        return []
    normalized: List[BaseMessage] = []
    for idx, m in enumerate(raw):
        # 1) Already a subclass?
        if isinstance(
            m,
            (
                HumanMessage,
                AIMessage,
                SystemMessage,
                ToolMessage,
                FunctionMessage,
            ),
        ):
            # Skip empty HumanMessages because some LLM APIs reject them
            if isinstance(m, HumanMessage) and not str(getattr(m, "content", "") or "").strip():
                logger.warning(f"Skipping empty HumanMessage instance at index {idx}")
                continue
            normalized.append(m)
            continue

        t = getattr(m, "type", "").lower()
        content = getattr(m, "content", None)
        if content is None:
            raise HTTPException(400, detail="message[{idx}].content is missing")

        # Grab raw additional_kwargs so we can pull out tool_calls/refusal
        raw_additional = getattr(m, "additional_kwargs", {}) or {}
        raw_tool_calls = getattr(m, "tool_calls", None) or raw_additional.get("tool_calls")
        raw_refusal = raw_additional.get("refusal")

        # Everything else (e.g. token_usage, model_name, id, etc) lives in response_metadata
        extra = getattr(m, "response_metadata", {}) or {}

        if t in ("human", "user"):
            # Skip empty user messages because some LLM APIs reject them
            if not str(content).strip():
                logger.warning(f"Skipping empty user message at index {idx}")
                continue
            normalized.append(HumanMessage(content=content, **extra))

        elif t in ("ai", "assistant"):
            # Build your kwargs explicitly
            ai_kwargs: Dict[str, Any] = {"content": content}

            # Re-inject refusal if present
            if raw_refusal is not None:
                ai_kwargs["refusal"] = raw_refusal

            # Turn each legacy entry into a proper tool_call dict
            normalized_tool_calls = []
            if raw_tool_calls:
                for tc in raw_tool_calls:
                    func = tc.get("function", tc)
                    # parse arguments JSON if needed:
                    raw_args = func.get("args", func.get("arguments", {}))
                    args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    # A stable id is mandatory: ToolMessages are matched to tool
                    # calls by id, and a missing id makes the pair invalid.
                    call_id = tc.get("id") or func.get("id") or f"call_{uuid.uuid4().hex[:24]}"
                    normalized_tool_calls.append(
                        {
                            "id": str(call_id),
                            "name": func.get("name"),
                            "args": args,
                            "type": "tool_call",
                        }
                    )
                # Assign the properly structured tool calls to ai_kwargs
                ai_kwargs["tool_calls"] = normalized_tool_calls

            # Ensure additional_kwargs is completely preserved (important for reasoning_content)
            ai_kwargs["additional_kwargs"] = dict(raw_additional) if raw_additional else {}
            if normalized_tool_calls and "reasoning_content" not in ai_kwargs["additional_kwargs"]:
                # Fallback for old/broken message histories that lost additional_kwargs
                # Moonshot kimi-k2.6 throws 400 Bad Request if reasoning_content is missing
                # on a tool_call message
                ai_kwargs["additional_kwargs"]["reasoning_content"] = ""
            # Finally merge in the other metadata (token_usage, model_name, etc)
            ai_kwargs.update(extra)

            normalized.append(AIMessage(**ai_kwargs))

        elif t == "system":
            normalized.append(SystemMessage(content=content, **extra))

        elif t == "tool":
            # Tool results MUST be preserved. Dropping them left the preceding
            # AIMessage.tool_calls unpaired, and every later turn then failed with
            # INVALID_CHAT_HISTORY ("AIMessages with tool_calls that do not have a
            # corresponding ToolMessage") - which looks like "tools stop working
            # after the first call".
            tool_call_id = (
                getattr(m, "tool_call_id", None)
                or getattr(m, "tool", None)  # some clients send the call id as `tool`
                or _extract_tool_call_id(m)
            )
            tool_name = getattr(m, "name", None)
            if not tool_call_id:
                # A tool output is never a user instruction. Older clients lost
                # the pairing metadata; omit these invalid protocol messages.
                logger.warning("Skipping tool result without call ID at index %s", idx)
                continue
            kwargs = {"content": content, "tool_call_id": str(tool_call_id)}
            if tool_name:
                kwargs["name"] = tool_name
            if getattr(m, "status", None):
                kwargs["status"] = m.status
            normalized.append(ToolMessage(**kwargs))

        elif t == "function":
            # Legacy function messages: keep them rather than silently dropping.
            normalized.append(
                FunctionMessage(
                    name=getattr(m, "name", "unknown_function"),
                    content=content,
                    **extra,
                )
            )

        else:
            raise HTTPException(400, detail="message[{idx}].type '{t}' not recognized")

    return _drop_orphan_tool_calls(normalized)


def _drop_orphan_tool_calls(messages: List[BaseMessage]) -> List[BaseMessage]:
    """Keep only adjacent, paired tool exchanges, including after history pruning."""
    fixed: List[BaseMessage] = []
    index = 0
    while index < len(messages):
        msg = messages[index]
        index += 1
        if isinstance(msg, ToolMessage):
            # Unmatched results (including a truncated prefix) cannot be sent
            # to a provider, and must not be relabelled as HumanMessages.
            continue
        if isinstance(msg, AIMessage) and msg.tool_calls:
            results = []
            while index < len(messages) and isinstance(messages[index], ToolMessage):
                results.append(messages[index])
                index += 1
            answered = {result.tool_call_id for result in results}
            kept = [tc for tc in msg.tool_calls if tc.get("id") in answered]
            additional = dict(msg.additional_kwargs)
            # Canonical calls are the source of truth. Stale legacy calls must
            # not reappear when the message is serialized for the next turn.
            additional.pop("tool_calls", None)
            msg = msg.model_copy(update={"tool_calls": kept, "additional_kwargs": additional})
            if not kept:
                if msg.content:
                    fixed.append(msg)
                continue
            fixed.append(msg)
            pending = {tc["id"] for tc in kept}
            for result in results:
                if result.tool_call_id in pending:
                    fixed.append(result)
                    pending.remove(result.tool_call_id)
            continue
        fixed.append(msg)
    return fixed


def _without_memory_context(messages: List[BaseMessage]) -> List[BaseMessage]:
    """Remove internal memory context system message from history."""
    if not messages:
        return []
    filtered = []
    for msg in messages:
        content = getattr(msg, "content", "")
        is_mem = isinstance(msg, SystemMessage) and (
            "<memory_context>" in str(content) or "</memory_context>" in str(content)
        )
        if is_mem:
            continue
        filtered.append(msg)
    return filtered


def _get_plan_action(query: Optional[str]) -> str:
    """Return confirm/cancel/none for a user reply to a pending execution plan."""
    normalized = (query or "").strip().lower()
    if not normalized:
        return "none"

    cancel_terms = ("取消", "停止", "不执行", "cancel", "stop", "no")
    confirm_terms = (
        "确认",
        "执行",
        "同意",
        "可以",
        "开始",
        "confirm",
        "execute",
        "yes",
        "ok",
        "proceed",
    )
    if any(term in normalized for term in cancel_terms):
        return "cancel"
    if any(term in normalized for term in confirm_terms):
        return "confirm"
    return "none"


def _plan_with_status(plan: Optional[Dict[str, Any]], status: str) -> Optional[Dict[str, Any]]:
    if not plan:
        return None
    updated = dict(plan)
    updated["status"] = status
    return updated


def _get_request_plan_action(request: GeoAgentRequest) -> str:
    """Return the intended plan action, honoring plan status from the UI."""
    if not request.execution_plan:
        return "none"
    if isinstance(request.execution_plan, dict):
        plan_status = request.execution_plan.get("status")
        if plan_status == "confirmed":
            return "confirm"
        if plan_status == "cancelled":
            return "cancel"
    return _get_plan_action(request.query)


def _execution_plan_for_response(
    execution_plan: Optional[Dict[str, Any]],
    fallback_plan: Optional[Dict[str, Any]],
    plan_action: str,
) -> Optional[Dict[str, Any]]:
    """Keep confirmed executions from leaking an older pending plan back to the UI."""
    if plan_action != "confirm":
        return execution_plan
    return _plan_with_status(execution_plan or fallback_plan, "confirmed")


def _is_unconfirmed_pending_plan(request: GeoAgentRequest, plan_action: str) -> bool:
    if plan_action != "none" or not isinstance(request.execution_plan, dict):
        return False
    return request.execution_plan.get("status") == "pending"


def _messages_with_request_query(request: GeoAgentRequest) -> List[BaseMessage]:
    messages = normalize_messages(request.messages)
    query_text = (request.query or "").strip()
    already_present = (
        messages
        and isinstance(messages[-1], HumanMessage)
        and str(messages[-1].content).strip() == query_text
    )
    if query_text and not already_present:
        messages.append(HumanMessage(query_text))
    return messages


def _messages_for_response(
    request: GeoAgentRequest, result_messages: List[BaseMessage]
) -> List[BaseMessage]:
    """Model context windows must not truncate or rewrite the visible transcript."""
    from services.conversation.store import select_messages_for_current_turn

    return _without_memory_context(
        _messages_with_request_query(request)
        + select_messages_for_current_turn(request.query, result_messages)
    )


router = APIRouter()


async def _prepare_chat_context(
    request: GeoAgentRequest,
    raw_request: Request,
    metrics,
    db: Optional[AsyncSession] = None,
    suppress_plan_tool: bool = False,
) -> tuple:
    """Prepare shared context for both chat and streaming endpoints.

    Normalizes messages, resolves session_id, manages message history
    (via pruning or summarization), and creates the agent + initial state.

    Args:
        request: The GeoAgent chat request
        raw_request: The raw FastAPI request (for cookies)
        metrics: Performance metrics tracker
        db: Optional SQLAlchemy database session

    Returns:
        Tuple of (state, single_agent, options, perf_callback, session_id, stream_id)
    """
    from services.single_agent import create_geo_agent, prepare_messages
    from utility.performance_metrics import PerformanceCallbackHandler

    # Normalize incoming messages and append user query
    messages: List[BaseMessage] = normalize_messages(request.messages)

    # Only append user query if it's non-empty and not already the last message
    # (the frontend's appendHumanMessage already adds it to request.messages)
    query_text = (request.query or "").strip()
    if query_text:
        # Check if the last message is already the same human message to avoid duplicates
        already_present = (
            messages
            and isinstance(messages[-1], HumanMessage)
            and str(messages[-1].content).strip() == query_text
        )
        if not already_present:
            messages.append(HumanMessage(query_text))
        else:
            logger.debug(
                "Skipping duplicate HumanMessage append: " "query already present as last message"
            )
    else:
        logger.warning("Received empty/None query in chat request")

    # Track message count before processing
    metrics.record("message_count_before", len(messages))

    # Parse options
    options_orig: dict = request.options
    options: SettingsSnapshot = SettingsSnapshot.model_validate(options_orig, strict=False)

    # Resolve session_id: options > cookie
    if not options.session_id:
        cookie_session_id = raw_request.cookies.get("session_id")
        if cookie_session_id:
            logger.info(f"Using session_id from cookie: {cookie_session_id}")
            options.session_id = cookie_session_id
        else:
            logger.warning("No session_id provided in options or cookies")

    session_id = getattr(options, "session_id", None) or "unknown"

    # Inject memory context if enabled
    enable_memory = getattr(options.model_settings, "enable_memory", True)
    if enable_memory:
        user_id = None
        try:
            from api.memory import _optional_user_id

            user_id = _optional_user_id(raw_request)
        except Exception as e:
            logger.warning(f"Failed to retrieve user_id for memory: {e}")

        user_id_str = str(user_id) if user_id else None

        short_mem = ""
        if getattr(options.model_settings, "enable_short_term_memory", True):
            try:
                from services.memory.short_term_memory import read_short_memory

                short_mem = read_short_memory(user_id_str, options.session_id)
            except Exception as e:
                logger.error(f"Failed to read short-term memory: {e}")

        long_mem = ""
        enable_long_term = getattr(options.model_settings, "enable_long_term_memory", False)
        if enable_long_term and user_id and db:
            try:
                from services.memory.long_term_memory import (
                    memories_to_context,
                    retrieve_relevant_memories,
                )

                memories = await retrieve_relevant_memories(
                    db, user_id=user_id, query=request.query
                )
                long_mem = memories_to_context(memories)
            except Exception as e:
                logger.error(f"Failed to retrieve long-term memories: {e}")

        if short_mem.strip() or long_mem.strip():
            try:
                from services.memory.short_term_memory import format_memory_context

                memory_context_text = format_memory_context(short_mem, long_mem)
                # Inject it as a SystemMessage at the start of messages
                messages.insert(0, SystemMessage(content=memory_context_text))
            except Exception as e:
                logger.error(f"Failed to format/inject memory context: {e}")

    # Get message window size from model settings or environment
    message_window_size = getattr(options.model_settings, "message_window_size", None)
    if message_window_size is None:
        import os

        message_window_size = int(os.getenv("MESSAGE_WINDOW_SIZE", "20"))

    # Create agent (returns agent + llm for summarization)
    enable_parallel_tools = getattr(options.model_settings, "enable_parallel_tools", False)

    # Get enabled MCP servers from options (pass full objects for auth)
    mcp_servers = [server for server in getattr(options, "mcp_servers", []) if server.enabled]

    confirmed_plan_tools = None
    if suppress_plan_tool and isinstance(request.execution_plan, dict):
        confirmed_plan_tools = [
            step.get("tool")
            for step in request.execution_plan.get("steps", [])
            if isinstance(step, dict) and step.get("tool")
        ]
    single_agent, llm = await create_geo_agent(
        model_settings=options.model_settings,
        selected_tools=options.tools,
        enable_parallel_tools=enable_parallel_tools,
        query=request.query,
        session_id=options.session_id,
        mcp_servers=mcp_servers if mcp_servers else None,
        suppress_plan_tool=suppress_plan_tool,
        confirmed_plan_tools=confirmed_plan_tools,
    )

    # Get message management mode from settings (or fall back to env var)
    message_management_mode = getattr(options.model_settings, "message_management_mode", None)

    # Prepare messages (summarization or pruning based on settings/env)
    messages = await prepare_messages(
        messages=messages,
        message_window_size=message_window_size,
        session_id=options.session_id,
        llm=llm,
        settings_mode=message_management_mode,
    )
    messages = _drop_orphan_tool_calls(messages)

    # Track message count after processing
    metrics.record("message_count_after", len(messages))
    metrics.record("message_reduction", metrics.metrics["message_count_before"] - len(messages))

    execution_plan = request.execution_plan
    if suppress_plan_tool:
        execution_plan = _plan_with_status(execution_plan, "confirmed")

    # Create initial state
    state: GeoDataAgentState = GeoDataAgentState(
        messages=messages,
        geodata_last_results=request.geodata_last_results,
        geodata_layers=request.geodata_layers,
        results_title="",
        geodata_results=[],
        options=options,
        remaining_steps=10,
        execution_plan=execution_plan,
    )

    # Create performance callback handler
    perf_callback = PerformanceCallbackHandler()

    # Also extract stream_id for cancellation tracking (streaming only)
    stream_id = options_orig.get("stream_id") or session_id

    return state, single_agent, options, perf_callback, session_id, stream_id


@router.post("/chatmock", tags=["nalamap"], response_model=GeoAgentResponse)
async def ask_nalamap(request: GeoAgentRequest):
    """
    Ask a question to the GeoAgent, which
    """
    # TODO: Pass information to agent

    # TODO: Receive response and map to result

    # Fake response for now
    messages: List[BaseMessage] = [
        HumanMessage("Find rivers in Africa!"),
        AIMessage("I found some rivers!"),
    ]

    response: GeoAgentResponse = GeoAgentResponse(
        messages=messages,
        response="I found some rivers!",
        geodata=mock_geodata_objects(),
        options=request.options,
    )
    return response


@router.post("/chat2", tags=["nalamap"], response_model=GeoAgentResponse)
async def ask_nalamap_orchestrator(request: GeoAgentRequest):
    """Ask a question to the GeoAgent Orchestrator, which uses tools to respond
    and analyse geospatial information."""
    # Lazy import: only load heavy modules when chat endpoint is actually called
    from services.multi_agent_orch import multi_agent_executor

    messages: List[BaseMessage] = normalize_messages(request.messages)
    messages.append(HumanMessage(request.query))

    state = DataState(messages=messages, geodata=request.geodata)

    executor_result: DataState = await multi_agent_executor.ainvoke(state)

    # print(executor_result)
    # print(executor_result['geodata'])
    # print(getattr(executor_result, "geodata", state["geodata"]))
    result_messages: List[BaseMessage] = executor_result["messages"]
    result_response: str = result_messages[-1].content
    result_geodata: List[GeoDataObject] = executor_result["geodata"]
    response: GeoAgentResponse = GeoAgentResponse(
        messages=result_messages,
        response=result_response,
        geodata=result_geodata,
        options=request.options,
    )
    return response


@router.post("/chat", tags=["nalamap"], response_model=GeoAgentResponse)
async def ask_nalamap_agent(
    request: GeoAgentRequest,
    raw_request: Request,
    db: AsyncSession = Depends(get_session),
):
    """Ask a question to the GeoAgent Single Agent, which uses tools to respond
    and analyse geospatial information."""
    # Lazy import: only load heavy modules when chat endpoint is actually called
    import openai

    from utility.metrics_storage import get_metrics_storage
    from utility.performance_metrics import (
        PerformanceMetrics,
        extract_token_usage_from_messages,
    )

    # Initialize performance tracking
    metrics = PerformanceMetrics()

    plan_action = _get_request_plan_action(request)
    if request.execution_plan and plan_action == "cancel":
        cancelled_plan = _plan_with_status(request.execution_plan, "cancelled")
        messages = normalize_messages(request.messages)
        if request.query:
            messages.append(HumanMessage(request.query))
        messages.append(AIMessage(content="已取消执行计划。"))
        return GeoAgentResponse(
            messages=_without_memory_context(messages),
            results_title="",
            geodata_results=[],
            geodata_layers=request.geodata_layers or [],
            execution_plan=cancelled_plan,
            options=request.options,
        )

    if request.execution_plan and _is_unconfirmed_pending_plan(request, plan_action):
        messages = _messages_with_request_query(request)
        messages.append(
            AIMessage(content="执行计划尚未确认。请回复“确认”开始执行，或回复“取消”放弃。")
        )
        return GeoAgentResponse(
            messages=_without_memory_context(messages),
            results_title="",
            geodata_results=[],
            geodata_layers=request.geodata_layers or [],
            execution_plan=request.execution_plan,
            options=request.options,
        )

    suppress_plan_tool = False
    if request.execution_plan and plan_action == "confirm":
        request.execution_plan = _plan_with_status(request.execution_plan, "confirmed")
        suppress_plan_tool = True

    # Prepare shared context (messages, agent, state)
    state, single_agent, options, perf_callback, session_id, stream_id = (
        await _prepare_chat_context(
            request, raw_request, metrics, db, suppress_plan_tool=suppress_plan_tool
        )
    )
    execution_plan = state.get("execution_plan")

    from services.agent_audit import AgentRunRecorder

    audit_recorder = AgentRunRecorder.from_options(db, options)
    audit_callback = audit_recorder.callback_handler()
    user_id = None
    try:
        from api.memory import _optional_user_id

        user_id = _optional_user_id(raw_request)
    except Exception as e:
        logger.warning(f"Failed to retrieve user_id for agent audit: {e}")

    await audit_recorder.start_run(
        endpoint="/chat",
        request=request,
        state=state,
        options=options,
        session_id=session_id,
        stream_id=stream_id,
        user_id=user_id,
    )

    try:
        # Enable langgraph debug logging when global log level is DEBUG
        debug_enabled = logger.isEnabledFor(logging.DEBUG)

        # Start timing agent execution
        metrics.start_timer("agent_execution")

        callbacks = [perf_callback]
        if audit_recorder.enabled:
            callbacks.append(audit_callback)

        run_config = build_agent_run_config(
            callbacks=callbacks,
            recursion_limit=AGENT_RECURSION_LIMIT,
            options=options,
            session_id=session_id,
            endpoint="/chat",
            audit_run_id=getattr(audit_recorder, "run_id", None),
        )

        try:
            # Match the streaming endpoint's budget (see /chat/stream). The old
            # default of 25 caused multi-step geo tasks to die with a
            # GraphRecursionError and surface as a generic 500, even though the
            # same request succeeded over SSE.
            executor_result: GeoDataAgentState = single_agent.invoke(
                state,
                debug=debug_enabled,
                config=run_config,
            )
        except TypeError as e:
            invoke_func = getattr(single_agent.invoke, "__func__", None)
            if "multiple values for argument 'debug'" not in str(e) or invoke_func is None:
                raise
            executor_result = invoke_func(
                state,
                debug=debug_enabled,
                config=run_config,
            )

        # End timing agent execution
        metrics.end_timer("agent_execution")

        result_messages: List[BaseMessage] = executor_result.get("messages", [])
        results_title: Optional[str] = executor_result.get("results_title", "")
        geodata_results: List[GeoDataObject] = executor_result.get("geodata_results", [])
        geodata_layers: List[GeoDataObject] = executor_result.get("geodata_layers", [])
        execution_plan = _execution_plan_for_response(
            executor_result.get("execution_plan"),
            state.get("execution_plan"),
            plan_action,
        )
        if execution_plan is not None:
            executor_result["execution_plan"] = execution_plan

        # Fallback: extract plan from AI text when model did not call the tool
        if (
            not execution_plan
            and plan_action == "none"
            and getattr(options.model_settings, "plan_mode", False)
        ):
            from api.plan_fallback import maybe_extract_plan_from_messages

            extracted = maybe_extract_plan_from_messages(result_messages)
            if extracted:
                execution_plan = extracted
                executor_result["execution_plan"] = execution_plan
                logger.info("Extracted execution plan from AI message text (fallback)")

        result_options: Dict[str, Any] = executor_result.get("options", {})

        # Track final message count
        metrics.record("message_count_final", len(result_messages))

        # Collect metrics from callback handler
        callback_metrics = perf_callback.get_metrics()
        metrics.metrics.update(callback_metrics)

        # Collect tool selector metrics (Week 3 - Performance Monitoring)
        from services.tool_selector import get_last_selector_metrics

        tool_selector_metrics = get_last_selector_metrics()
        if tool_selector_metrics:
            metrics.metrics["tool_selector"] = tool_selector_metrics

        # Extract token usage from messages if not captured by callback
        if callback_metrics["token_usage"]["total"] == 0:
            token_usage = extract_token_usage_from_messages(result_messages)
            metrics.metrics["token_usage"] = token_usage

        # Track state metrics
        metrics.record("geodata_layers_count", len(geodata_layers))
        metrics.record("geodata_results_count", len(geodata_results))

        # Log performance metrics
        final_metrics = metrics.finalize()

        # Store metrics in global storage if enabled
        session_id = getattr(options, "session_id", None) or "unknown"
        conversation_id = getattr(options, "conversation_id", None) or session_id
        final_metrics["conversation_id"] = conversation_id
        enable_performance_metrics = getattr(
            options.model_settings, "enable_performance_metrics", False
        )
        if enable_performance_metrics:
            storage = get_metrics_storage()
            storage.store(
                session_id=session_id,
                conversation_id=conversation_id,
                metrics=final_metrics,
            )

        logger.info(
            "Agent execution completed",
            extra={
                "performance_metrics": final_metrics,
                "session_id": session_id,
                "conversation_id": conversation_id,
            },
        )

        await audit_recorder.record_events(audit_callback.events)
        await audit_recorder.finish_run(
            status="success",
            final_state=executor_result,
            output_messages=_without_memory_context(result_messages),
            metrics=final_metrics,
        )
        await _persist_conversation_turn(
            options=options,
            session_id=session_id,
            user_id=user_id,
            query=getattr(request, "query", None),
            result_messages=_without_memory_context(result_messages),
            geodata_layers=geodata_layers,
            run_id=(
                getattr(audit_recorder, "run_id", None)
                if getattr(audit_recorder, "enabled", False)
                else None
            ),
        )
        if not result_messages:  # Should always have messages, but safeguard
            result_messages = [
                AIMessage(content="Agent processed the request but returned no explicit messages.")
            ]

    except openai.InternalServerError as e:
        logger.error(f"OpenAI Internal Server Error: {e}")
        error_message = (
            "I encountered an issue with the AI model while processing your request. "
            "This might be a temporary problem. Please try again in a few moments. "
            "If the problem persists, simplifying your query might help."
        )
        result_messages = [
            *state.get("messages", []),
            AIMessage(content=error_message),
        ]  # Include history
        results_title = "Model Error"
        geodata_results = []
        geodata_layers = state.get("geodata_layers", [])  # Preserve existing layers
        execution_plan = state.get("execution_plan")
        # global_geodata = state.get('global_geodata', [])
        result_options = options
        await audit_recorder.record_events(audit_callback.events)
        await audit_recorder.finish_run(
            status="error",
            final_state={
                "messages": result_messages,
                "results_title": results_title,
                "geodata_results": geodata_results,
                "geodata_layers": geodata_layers,
                "execution_plan": execution_plan,
            },
            output_messages=_without_memory_context(result_messages),
            metrics=metrics.finalize(),
            error={"type": "model_error", "message": str(e)},
        )
    except openai.APIError as e:
        logger.error(f"OpenAI API Error: {e}")
        error_message = (
            "I encountered an API error while trying to process your request. "
            "Please check your query or try again later."
        )
        result_messages = [*state.get("messages", []), AIMessage(content=error_message)]
        results_title = "API Error"
        geodata_results = []
        geodata_layers = state.get("geodata_layers", [])
        execution_plan = state.get("execution_plan")
        # global_geodata = state.get('global_geodata', [])
        result_options = options
        await audit_recorder.record_events(audit_callback.events)
        await audit_recorder.finish_run(
            status="error",
            final_state={
                "messages": result_messages,
                "results_title": results_title,
                "geodata_results": geodata_results,
                "geodata_layers": geodata_layers,
                "execution_plan": execution_plan,
            },
            output_messages=_without_memory_context(result_messages),
            metrics=metrics.finalize(),
            error={"type": "api_error", "message": str(e)},
        )
    except Exception as e:  # Catch any other unexpected errors during agent execution
        logger.exception(f"Unexpected error during agent execution: {e}")
        if "Recursion limit" in str(e) or type(e).__name__ == "GraphRecursionError":
            error_message = (
                "任务步骤过多，已中止。通常是因为某个工具反复失败后仍被重试。"
                "建议缩小查询范围、指定具体数据源后重试；"
                "如果涉及多步空间分析，也可以改用流式接口。"
            )
            results_title = "任务中止"
        else:
            error_message = (
                "An unexpected error occurred while processing your request. " "Please try again."
            )
            results_title = "Unexpected Error"
        result_messages = [*state.get("messages", []), AIMessage(content=error_message)]
        geodata_results = []
        geodata_layers = state.get("geodata_layers", [])
        execution_plan = state.get("execution_plan")
        # global_geodata = state.get('global_geodata', [])
        result_options = options
        await audit_recorder.record_events(audit_callback.events)
        await audit_recorder.finish_run(
            status="error",
            final_state={
                "messages": result_messages,
                "results_title": results_title,
                "geodata_results": geodata_results,
                "geodata_layers": geodata_layers,
                "execution_plan": execution_plan,
            },
            output_messages=_without_memory_context(result_messages),
            metrics=metrics.finalize(),
            error={"type": "unexpected_error", "message": str(e)},
        )
    # Ensure results_title is set if geodata_results exist but title is empty
    if (
        (results_title is None or results_title == "")
        and geodata_results
        and isinstance(geodata_results, List)
        and len(geodata_results) != 0
    ):
        results_title = "Agent results:"

    # Ensure result_messages always has at least one message for response
    # construction
    if not result_messages:
        # This case should ideally be handled by the agent or error blocks,
        # but as a final fallback:
        result_messages = [AIMessage(content="No response content generated.")]

    response: GeoAgentResponse = GeoAgentResponse(
        messages=_messages_for_response(request, result_messages),
        results_title=results_title,
        geodata_results=geodata_results,
        geodata_layers=geodata_layers,
        execution_plan=execution_plan,
        # global_geodata=global_geodata,
        options=result_options,
    )
    return response


@router.post("/chat/stream", tags=["nalamap"])
async def ask_nalamap_agent_stream(
    request: GeoAgentRequest,
    raw_request: Request,
    db: AsyncSession = Depends(get_session),
):
    """
    Streaming version of the GeoAgent agent that emits real-time events
    using Server-Sent Events (SSE).

    Event types:
    - tool_start: Tool execution begins
    - tool_end: Tool execution completes
    - llm_token: LLM token streamed
    - state_update: Agent state changed
    - result: Final result ready
    - error: Error occurred
    - done: Stream complete
    """
    import json

    import openai
    from fastapi.responses import StreamingResponse

    from services.agent_audit import AgentRunRecorder
    from utility.metrics_storage import get_metrics_storage
    from utility.performance_metrics import (
        PerformanceMetrics,
        extract_token_usage_from_messages,
    )

    async def event_generator():
        """Generate SSE events from agent execution."""
        stream_id = "unknown"  # Initialize at function scope
        pending_event = None
        event_iter = None
        audit_recorder = AgentRunRecorder(db=None, enabled=False)
        audit_callback = audit_recorder.callback_handler()

        async def finish_audit(**kwargs):
            await audit_recorder.record_events(audit_callback.events)
            audit_callback.events.clear()
            await audit_recorder.finish_run(**kwargs)

        try:
            # Initialize performance tracking
            metrics = PerformanceMetrics()

            plan_action = _get_request_plan_action(request)
            if request.execution_plan and plan_action == "cancel":
                cancelled_plan = _plan_with_status(request.execution_plan, "cancelled")
                messages = normalize_messages(request.messages)
                if request.query:
                    messages.append(HumanMessage(request.query))
                messages.append(AIMessage(content="已取消执行计划。"))
                serialized_messages = [
                    make_json_serializable(msg) for msg in _without_memory_context(messages)
                ]
                yield "event: result\n"
                result_data = {
                    "messages": serialized_messages,
                    "results_title": "",
                    "geodata_results": [],
                    "geodata_layers": make_json_serializable(request.geodata_layers or []),
                    "execution_plan": cancelled_plan,
                    "metrics": metrics.finalize(),
                }
                yield f"data: {json.dumps(result_data)}\n\n"
                yield "event: done\n"
                yield f"data: {json.dumps({'status': 'complete'})}\n\n"
                return

            if request.execution_plan and _is_unconfirmed_pending_plan(request, plan_action):
                messages = _messages_with_request_query(request)
                messages.append(
                    AIMessage(content="执行计划尚未确认。请回复“确认”开始执行，或回复“取消”放弃。")
                )
                serialized_messages = [
                    make_json_serializable(msg) for msg in _without_memory_context(messages)
                ]
                yield "event: result\n"
                result_data = {
                    "messages": serialized_messages,
                    "results_title": "",
                    "geodata_results": [],
                    "geodata_layers": make_json_serializable(request.geodata_layers or []),
                    "execution_plan": request.execution_plan,
                    "metrics": metrics.finalize(),
                }
                yield f"data: {json.dumps(result_data)}\n\n"
                yield "event: done\n"
                yield f"data: {json.dumps({'status': 'complete'})}\n\n"
                return

            suppress_plan_tool = False
            if request.execution_plan and plan_action == "confirm":
                request.execution_plan = _plan_with_status(request.execution_plan, "confirmed")
                suppress_plan_tool = True

            # Prepare shared context (messages, agent, state)
            (
                state,
                single_agent,
                options,
                perf_callback,
                session_id,
                stream_id,
            ) = await _prepare_chat_context(
                request,
                raw_request,
                metrics,
                db,
                suppress_plan_tool=suppress_plan_tool,
            )

            audit_recorder = AgentRunRecorder.from_options(db, options)
            audit_callback = audit_recorder.callback_handler(capture_tool_events=False)
            user_id = None
            try:
                from api.memory import _optional_user_id

                user_id = _optional_user_id(raw_request)
            except Exception as e:
                logger.warning(f"Failed to retrieve user_id for agent audit: {e}")

            await audit_recorder.start_run(
                endpoint="/chat/stream",
                request=request,
                state=state,
                options=options,
                session_id=session_id,
                stream_id=stream_id,
                user_id=user_id,
            )

            # Start timing
            metrics.start_timer("agent_execution")

            # Stream events using astream_events v2
            _pending_tools: Dict[str, Dict[str, Any]] = {}
            callbacks = [perf_callback]
            if audit_recorder.enabled:
                callbacks.append(audit_callback)

            run_config = build_agent_run_config(
                callbacks=callbacks,
                recursion_limit=AGENT_RECURSION_LIMIT,
                options=options,
                session_id=session_id,
                endpoint="/chat/stream",
                audit_run_id=getattr(audit_recorder, "run_id", None),
            )

            # Drive astream_events manually so we can poll cancel/disconnect while
            # waiting for the next event (LLM tokens / async tool waits). Sync tools
            # still block the event loop until they return; cancel takes effect at
            # the next event boundary after that.
            event_stream = single_agent.astream_events(
                state,
                version="v2",
                config=run_config,
            )
            event_iter = event_stream.__aiter__()

            async def _should_stop_stream() -> bool:
                if await is_cancelled(stream_id):
                    return True
                try:
                    if await raw_request.is_disconnected():
                        logger.info(
                            f"Client disconnected for stream: {stream_id}; "
                            "treating as cancellation"
                        )
                        async with _cancellation_lock:
                            _cancellation_flags[stream_id] = True
                        return True
                except Exception as disconnect_err:
                    logger.debug(f"is_disconnected check failed for {stream_id}: {disconnect_err}")
                return False

            while True:
                if await _should_stop_stream():
                    logger.warning(f"Cancellation detected for stream: {stream_id} at event loop")
                    await finish_audit(
                        status="cancelled",
                        final_state=state,
                        metrics=metrics.finalize(),
                        error={
                            "type": "cancelled",
                            "message": "Request cancelled by user",
                        },
                    )
                    yield "event: cancelled\n"
                    yield f"data: {json.dumps({'message': 'Request cancelled by user'})}\n\n"
                    yield "event: done\n"
                    yield f"data: {json.dumps({'status': 'cancelled'})}\n\n"
                    return

                # Poll the same task without cancelling __anext__ on every timeout.
                # wait_for would close the async generator whenever the model/tool
                # takes longer than 0.5 seconds to emit its next event.
                if pending_event is None:
                    pending_event = asyncio.ensure_future(event_iter.__anext__())
                done, _ = await asyncio.wait({pending_event}, timeout=0.5)
                if not done:
                    continue
                completed_event = pending_event
                pending_event = None
                try:
                    event = completed_event.result()
                except StopAsyncIteration:
                    break
                # Other exceptions must reach the SSE error handlers below.

                event_type = event.get("event")
                event_name = event.get("name", "")
                event_data = event.get("data", {})

                # Debug logging for cancellation checking
                if event_type in [
                    "on_tool_start",
                    "on_tool_end",
                    "on_tool_error",
                    "on_chain_start",
                ]:
                    logger.info(
                        f"Event: {event_type} | name: {event_name} | "
                        f"stream: {stream_id} | cancelled: {await is_cancelled(stream_id)}"
                    )

                # Debug logging for all events (including tool events)
                if event_type in ["on_chain_start", "on_chain_end"]:
                    logger.info(f"Chain event: type={event_type}, name={event_name}")
                elif event_type not in [
                    "on_tool_start",
                    "on_tool_end",
                    "on_tool_error",
                    "on_chat_model_stream",
                ]:
                    # Log any unexpected/unknown event types to help diagnose missing events
                    logger.debug(f"Other event: type={event_type}, name={event_name}")

                # ---- Track running tools for synthetic completion events ----
                # LangGraph tools that return Command objects do NOT emit
                # on_tool_end via astream_events v2. We track which tools have
                # started and, when the "tools" chain node ends, emit synthetic
                # tool_end events for any tools that never received one.

                # Handle tool events
                if event_type == "on_tool_start":
                    tool_name = event_name
                    tool_input = event_data.get("input", {})
                    serializable_input = make_json_serializable(tool_input)
                    tool_call_id = _ensure_tool_call_id(
                        tool_name,
                        _extract_tool_call_id(serializable_input),
                        event.get("run_id"),
                    )
                    tool_key = _tool_event_key(tool_name, tool_call_id, event.get("run_id"))
                    _pending_tools[tool_key] = {
                        "tool": tool_name,
                        "tool_call_id": tool_call_id,
                        "input": serializable_input,
                    }
                    start_data = {
                        "tool": tool_name,
                        "tool_call_id": tool_call_id,
                        "input": serializable_input,
                    }
                    await audit_recorder.record_event(
                        "tool_start",
                        name=tool_name,
                        input_data=start_data,
                        payload={"tool_call_id": tool_call_id, "tool_key": tool_key},
                    )
                    yield "event: tool_start\n"
                    data = json.dumps(start_data)
                    yield f"data: {data}\n\n"
                elif event_type == "on_tool_end":
                    tool_name = event_name
                    tool_output = event_data.get("output", {})
                    tool_call_id = _extract_tool_call_id(tool_output)
                    tool_key = _tool_event_key(tool_name, tool_call_id, event.get("run_id"))
                    pending = _pending_tools.pop(tool_key, None)
                    if pending and not tool_call_id:
                        tool_call_id = pending.get("tool_call_id")
                    tool_call_id = _ensure_tool_call_id(
                        tool_name, tool_call_id, event.get("run_id")
                    )
                    output_data = _build_tool_output_data(
                        tool_name,
                        tool_output,
                        tool_call_id=tool_call_id,
                    )

                    await audit_recorder.record_event(
                        "tool_end",
                        name=tool_name,
                        output_data=output_data,
                        payload={"tool_call_id": tool_call_id, "tool_key": tool_key},
                    )
                    if output_data.get("is_state_update"):
                        await audit_recorder.record_event(
                            "state_update",
                            name=tool_name,
                            output_data={
                                "parent_tool_call_id": tool_call_id,
                                "tool": tool_name,
                                "status": output_data.get("status"),
                                "output_type": output_data.get("output_type"),
                            },
                            payload={"parent_tool_call_id": tool_call_id},
                        )
                    yield "event: tool_end\n"
                    data = json.dumps(output_data)
                    yield f"data: {data}\n\n"
                elif event_type == "on_tool_error":
                    tool_name = event_name
                    error_msg = str(event_data.get("error", "Unknown tool error"))
                    tool_call_id = _extract_tool_call_id(event_data)
                    tool_key = _tool_event_key(tool_name, tool_call_id, event.get("run_id"))
                    pending = _pending_tools.pop(tool_key, None)
                    if pending and not tool_call_id:
                        tool_call_id = pending.get("tool_call_id")
                    tool_call_id = _ensure_tool_call_id(
                        tool_name, tool_call_id, event.get("run_id")
                    )
                    logger.error(f"Tool execution failed: {tool_name} - {error_msg}")
                    output_data = {
                        "tool": tool_name,
                        "tool_call_id": tool_call_id,
                        "status": "failed",
                        "output": {"error": error_msg},
                        "output_preview": f"Error: {error_msg[:200]}",
                        "error_message": error_msg,
                        "is_state_update": False,
                        "output_type": "error",
                    }
                    await audit_recorder.record_event(
                        "tool_error",
                        name=tool_name,
                        output_data=output_data,
                        payload={"tool_call_id": tool_call_id, "tool_key": tool_key},
                    )
                    yield "event: tool_end\n"
                    data = json.dumps(output_data)
                    yield f"data: {data}\n\n"
                # Handle LLM streaming tokens
                elif event_type == "on_chat_model_stream":
                    chunk = event_data.get("chunk", {})
                    if hasattr(chunk, "content") and chunk.content:
                        yield "event: llm_token\n"
                        yield f"data: {json.dumps({'token': chunk.content})}\n\n"

                # Handle chain/agent state updates
                elif event_type == "on_chain_end":
                    # Emit synthetic tool_end for Command-returning tools
                    # The "tools" chain node ends after all tools in a batch finish.
                    if event_name == "tools" and _pending_tools:
                        for tool_key, pending in list(_pending_tools.items()):
                            pending_tool_name = pending.get("tool", "unknown")
                            tool_call_id = _ensure_tool_call_id(
                                pending_tool_name, pending.get("tool_call_id"), tool_key
                            )
                            logger.info(
                                "Synthetic tool_end for Command-returning tool: "
                                f"{pending_tool_name}"
                            )
                            output_data = {
                                "tool": pending_tool_name,
                                "tool_call_id": tool_call_id,
                                "status": "success",
                                "output_preview": "Completed (state updated)",
                                "error_message": None,
                                "is_state_update": True,
                                "output_type": "command",
                            }
                            await audit_recorder.record_event(
                                "tool_end",
                                name=pending_tool_name,
                                output_data=output_data,
                                payload={
                                    "tool_call_id": tool_call_id,
                                    "tool_key": tool_key,
                                },
                            )
                            await audit_recorder.record_event(
                                "state_update",
                                name=pending_tool_name,
                                output_data={
                                    "parent_tool_call_id": tool_call_id,
                                    "tool": pending_tool_name,
                                    "status": "success",
                                    "output_type": "command",
                                },
                                payload={"parent_tool_call_id": tool_call_id},
                            )
                            yield "event: tool_end\n"
                            data = json.dumps(output_data)
                            yield f"data: {data}\n\n"
                        _pending_tools.clear()
                    # Check for both "LangGraph" (older) and "GeoAgent" (current name)
                    if event_name in ["LangGraph", "GeoAgent"]:
                        # Agent execution complete - get final state
                        output = event_data.get("output", {})

                        execution_plan = _execution_plan_for_response(
                            output.get("execution_plan"),
                            state.get("execution_plan"),
                            plan_action,
                        )
                        if execution_plan is not None:
                            output["execution_plan"] = execution_plan

                        # Fallback: extract plan from AI text when model did not call the tool
                        if (
                            not execution_plan
                            and plan_action == "none"
                            and getattr(options.model_settings, "plan_mode", False)
                        ):
                            from api.plan_fallback import (
                                maybe_extract_plan_from_messages,
                            )

                            extracted = maybe_extract_plan_from_messages(output.get("messages", []))
                            if extracted:
                                execution_plan = extracted
                                output["execution_plan"] = execution_plan
                                logger.info(
                                    "Extracted execution plan from AI message text (fallback)"
                                )

                        # Plan Mode: Check if there's a newly pending execution plan.
                        if (
                            plan_action != "confirm"
                            and execution_plan
                            and isinstance(execution_plan, dict)
                            and execution_plan.get("status") == "pending"
                        ):
                            yield "event: plan_created\n"
                            yield f"data: {json.dumps(make_json_serializable(execution_plan))}\n\n"
                        result_messages = output.get("messages", [])
                        results_title = output.get("results_title", "")
                        geodata_results = output.get("geodata_results", [])
                        geodata_layers = output.get("geodata_layers", [])
                        execution_plan = output.get("execution_plan")

                        # End timing
                        metrics.end_timer("agent_execution")

                        # Collect metrics
                        callback_metrics = perf_callback.get_metrics()
                        metrics.metrics.update(callback_metrics)

                        # Extract token usage if needed
                        if callback_metrics["token_usage"]["total"] == 0:
                            token_usage = extract_token_usage_from_messages(result_messages)
                            metrics.metrics["token_usage"] = token_usage

                        # Track state metrics
                        metrics.record("geodata_layers_count", len(geodata_layers))
                        metrics.record("geodata_results_count", len(geodata_results))
                        metrics.record("message_count_final", len(result_messages))

                        # Finalize and store metrics
                        final_metrics = metrics.finalize()
                        session_id = getattr(options, "session_id", None) or "unknown"
                        conversation_id = getattr(options, "conversation_id", None) or session_id
                        final_metrics["conversation_id"] = conversation_id
                        enable_performance_metrics = getattr(
                            options.model_settings, "enable_performance_metrics", False
                        )
                        if enable_performance_metrics:
                            storage = get_metrics_storage()
                            storage.store(
                                session_id=session_id,
                                conversation_id=conversation_id,
                                metrics=final_metrics,
                            )

                        logger.info(
                            "Agent execution completed (streaming)",
                            extra={
                                "performance_metrics": final_metrics,
                                "session_id": session_id,
                                "conversation_id": conversation_id,
                            },
                        )

                        # Send final result
                        # Convert messages to serializable format (client-safe size).
                        serializable_messages = []
                        for msg in _messages_for_response(request, result_messages):
                            serializable_messages.append(
                                make_json_serializable(msg, for_client=True)
                            )

                        # Serialize geodata objects
                        serialized_results = [
                            r.model_dump() if hasattr(r, "model_dump") else r
                            for r in geodata_results
                        ]
                        serialized_layers = [
                            (layer.model_dump() if hasattr(layer, "model_dump") else layer)
                            for layer in geodata_layers
                        ]

                        yield "event: result\n"
                        result_data = {
                            "messages": serializable_messages,
                            "results_title": results_title,
                            "geodata_results": serialized_results,
                            "geodata_layers": serialized_layers,
                            "execution_plan": make_json_serializable(execution_plan),
                            "metrics": final_metrics,
                        }
                        await finish_audit(
                            status="success",
                            final_state=output,
                            output_messages=serializable_messages,
                            metrics=final_metrics,
                        )
                        await _persist_conversation_turn(
                            options=options,
                            session_id=session_id,
                            user_id=user_id,
                            query=getattr(request, "query", None),
                            result_messages=serializable_messages,
                            geodata_layers=geodata_layers,
                            run_id=(
                                getattr(audit_recorder, "run_id", None)
                                if getattr(audit_recorder, "enabled", False)
                                else None
                            ),
                        )
                        yield f"data: {json.dumps(result_data)}\n\n"

            # Send done event
            yield "event: done\n"
            yield f"data: {json.dumps({'status': 'complete'})}\n\n"

        except openai.InternalServerError as e:
            logger.error(f"OpenAI Internal Server Error during streaming: {e}")
            await finish_audit(
                status="error",
                metrics=metrics.finalize() if "metrics" in locals() else None,
                error={"type": "model_error", "message": str(e)},
            )
            yield "event: error\n"
            yield f"data: {json.dumps({'error': 'model_error', 'message': str(e)})}\n\n"
            yield "event: done\n"
            yield f"data: {json.dumps({'status': 'error'})}\n\n"

        except openai.APIError as e:
            logger.error(f"OpenAI API Error during streaming: {e}")
            await finish_audit(
                status="error",
                metrics=metrics.finalize() if "metrics" in locals() else None,
                error={"type": "api_error", "message": str(e)},
            )
            yield "event: error\n"
            yield f"data: {json.dumps({'error': 'api_error', 'message': str(e)})}\n\n"
            yield "event: done\n"
            yield f"data: {json.dumps({'status': 'error'})}\n\n"

        except Exception as e:
            logger.exception(f"Unexpected error during streaming: {e}")
            if "Recursion limit" in str(e) or type(e).__name__ == "GraphRecursionError":
                stream_error = {
                    "error": "recursion_limit",
                    "message": (
                        "任务步骤过多，已中止。通常是因为某个工具反复失败后仍被重试。"
                        "建议缩小查询范围或指定具体数据源后重试。"
                    ),
                }
            else:
                stream_error = {"error": "unexpected_error", "message": str(e)}
            await finish_audit(
                status="error",
                metrics=metrics.finalize() if "metrics" in locals() else None,
                error={
                    "type": stream_error["error"],
                    "message": stream_error["message"],
                },
            )
            yield "event: error\n"
            yield f"data: {json.dumps(stream_error, ensure_ascii=False)}\n\n"
            yield "event: done\n"
            yield f"data: {json.dumps({'status': 'error'})}\n\n"

        finally:
            if pending_event is not None:
                pending_event.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await pending_event
            if event_iter is not None:
                try:
                    await event_iter.aclose()
                except Exception as close_err:
                    logger.debug(f"Failed to aclose event stream {stream_id}: {close_err}")
            # Always clear cancellation flag when stream ends (use stream_id)
            await clear_cancellation(stream_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _parse_vllm_prometheus_metrics(
    metrics_text: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Parse vLLM Prometheus text exposition into JSON-friendly samples."""
    parsed: Dict[str, List[Dict[str, Any]]] = {}
    for raw_line in metrics_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or " " not in line:
            continue

        series, raw_value = line.rsplit(None, 1)
        try:
            value = float(raw_value)
        except ValueError:
            continue

        labels: Dict[str, str] = {}
        metric_name = series
        if "{" in series and series.endswith("}"):
            metric_name, raw_labels = series.split("{", 1)
            labels = dict(re.findall(r'([a-zA-Z_][\w]*)="([^"]*)"', raw_labels[:-1]))

        if metric_name.startswith("vllm:"):
            parsed.setdefault(metric_name, []).append({"labels": labels, "value": value})

    return parsed


def _select_vllm_monitor_metrics(
    parsed_metrics: Dict[str, List[Dict[str, Any]]], include_all: bool
) -> Dict[str, List[Dict[str, Any]]]:
    if include_all:
        return parsed_metrics

    important_terms = (
        "num_requests",
        "cache_usage",
        "latency",
        "time_to_first_token",
        "tokens",
        "gpu",
    )
    return {
        name: samples
        for name, samples in parsed_metrics.items()
        if any(term in name for term in important_terms)
    }


@router.get("/metrics/vllm", tags=["nalamap"])
async def get_vllm_metrics(
    raw: bool = Query(default=False, description="Return raw Prometheus text"),
    include_all: bool = Query(default=False, description="Return all parsed vLLM metrics"),
):
    """Fetch vLLM Prometheus metrics from the configured vLLM server."""
    import httpx

    from services.ai.vllm import get_metrics_url

    metrics_url = get_metrics_url()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(metrics_url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch vLLM metrics from {metrics_url}: {exc}",
        ) from exc

    if raw:
        return Response(content=response.text, media_type="text/plain")

    parsed_metrics = _parse_vllm_prometheus_metrics(response.text)
    selected_metrics = _select_vllm_monitor_metrics(parsed_metrics, include_all)
    return {
        "status": "success",
        "source": metrics_url,
        "metric_count": len(selected_metrics),
        "available_metric_names": sorted(parsed_metrics.keys()),
        "metrics": selected_metrics,
    }


@router.get("/metrics", tags=["nalamap"])
async def get_metrics(
    hours: int = Query(default=1, ge=1, le=168, description="Hours to look back (1-168)"),
    session_id: Optional[str] = Query(default=None, description="Filter by session ID"),
    conversation_id: Optional[str] = Query(default=None, description="Filter by conversation ID"),
):
    """Get performance metrics for recent requests.

    Args:
        hours: Number of hours to look back (1-168, default: 1)
        session_id: Optional session ID filter

    Returns:
        Dictionary with recent metrics or aggregated statistics
    """
    from utility.metrics_storage import get_metrics_storage

    storage = get_metrics_storage()

    # Return aggregated statistics
    stats = storage.get_statistics(
        hours=hours, session_id=session_id, conversation_id=conversation_id
    )

    return {
        "status": "success",
        "data": stats,
        "storage_info": {"total_entries": storage.get_count()},
    }


@router.post("/chat/cancel", tags=["nalamap"])
async def cancel_chat_request(session_id: str):
    """
    Cancel an ongoing chat/streaming request for a specific stream.

    Args:
        session_id: The stream ID of the request to cancel (can be user session_id
                   for backward compatibility or stream_id for new requests)

    Returns:
        Status message indicating cancellation was requested
    """
    async with _cancellation_lock:
        _cancellation_flags[session_id] = True
        logger.info(f"Cancellation requested for stream: {session_id}")

    return {"status": "cancellation_requested", "session_id": session_id}


async def is_cancelled(session_id: str) -> bool:
    """Check if cancellation has been requested for a session."""
    async with _cancellation_lock:
        return _cancellation_flags.get(session_id, False)


async def clear_cancellation(session_id: str):
    """Clear cancellation flag for a session after completion."""
    async with _cancellation_lock:
        _cancellation_flags.pop(session_id, None)


@router.get("/metrics/recent", tags=["nalamap"])
async def get_recent_metrics(
    hours: int = Query(default=1, ge=1, le=24, description="Hours to look back (1-24)"),
    session_id: Optional[str] = Query(default=None, description="Filter by session ID"),
    conversation_id: Optional[str] = Query(default=None, description="Filter by conversation ID"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max results (1-1000)"),
):
    """Get recent raw metrics entries.

    Args:
        hours: Number of hours to look back (1-24, default: 1)
        session_id: Optional session ID filter
        limit: Maximum number of entries to return

    Returns:
        List of recent metrics entries
    """
    from utility.metrics_storage import get_metrics_storage

    storage = get_metrics_storage()
    recent = storage.get_recent(hours=hours, session_id=session_id, conversation_id=conversation_id)

    # Limit results
    recent = recent[-limit:]

    return {"status": "success", "data": recent, "count": len(recent)}
