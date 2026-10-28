"""Hard stop for identical tool calls that soft prompt constraints fail to curb.

Without this, a ReAct model can re-invoke geocode / attribute / etc. with the
same arguments until LangGraph hits ``recursion_limit`` and the user sees
「任务步骤过多，已中止」.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional, Set

from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)

# How many times the same (session, tool, normalized args) may run before refusal.
# Default 2 = one intentional attempt + one retry; the 3rd identical call is blocked.
TOOL_IDENTICAL_CALL_MAX = int(os.getenv("TOOL_IDENTICAL_CALL_MAX", "2"))

_IDENTICAL_CALL_COUNTS: Dict[str, int] = {}

# Keys that are injected by LangGraph / LangChain and must not affect fingerprints.
_IGNORED_ARG_KEYS: Set[str] = {
    "state",
    "tool_call_id",
    "config",
    "run_manager",
    "callbacks",
}


def _session_key(state: Any) -> str:
    options = state.get("options") if hasattr(state, "get") else None
    session_id = getattr(options, "session_id", None)
    if not session_id and isinstance(options, dict):
        session_id = options.get("session_id")
    return str(session_id or "unknown")


def fingerprint_tool_args(args: Dict[str, Any]) -> str:
    """Stable hash of tool arguments excluding injected/runtime fields."""
    cleaned: Dict[str, Any] = {}
    for key, value in (args or {}).items():
        if key in _IGNORED_ARG_KEYS:
            continue
        cleaned[key] = value
    payload = json.dumps(cleaned, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _counter_key(session_id: str, tool_name: str, fingerprint: str) -> str:
    return f"{session_id}::{tool_name}::{fingerprint}"


def reset_identical_call_counts(session_id: Optional[str] = None) -> None:
    """Clear counters (tests / session teardown)."""
    if session_id is None:
        _IDENTICAL_CALL_COUNTS.clear()
        return
    prefix = f"{session_id}::"
    for key in list(_IDENTICAL_CALL_COUNTS):
        if key.startswith(prefix):
            del _IDENTICAL_CALL_COUNTS[key]


def refuse_identical_tool_call(
    state: Any,
    tool_name: str,
    tool_call_id: str,
    args: Dict[str, Any],
    *,
    max_calls: Optional[int] = None,
) -> Optional[Command]:
    """Return a terminal ToolMessage Command when identical args exceed the budget.

    Call this at the start of a tool. On the first ``max_calls`` hits the counter
    increments and ``None`` is returned so the real tool body runs. Further
    identical calls get a hard refusal that tells the model to stop.
    """
    limit = TOOL_IDENTICAL_CALL_MAX if max_calls is None else max_calls
    if limit <= 0:
        return None

    session_id = _session_key(state)
    fingerprint = fingerprint_tool_args(args)
    key = _counter_key(session_id, tool_name, fingerprint)
    used = _IDENTICAL_CALL_COUNTS.get(key, 0)

    if used < limit:
        _IDENTICAL_CALL_COUNTS[key] = used + 1
        return None

    logger.warning(
        "Identical tool call blocked: tool=%s session=%s count=%d/%d fp=%s",
        tool_name,
        session_id,
        used,
        limit,
        fingerprint,
    )
    return Command(
        update={
            "messages": [
                ToolMessage(
                    name=tool_name,
                    content=(
                        f"Error: identical {tool_name} call already ran "
                        f"{used}/{limit} time(s) with the same arguments in this session. "
                        f"Do NOT call {tool_name} again with these arguments. "
                        "Use the previous tool result as final evidence. "
                        "If the user asked for a count or summary, answer from that "
                        "result now. If a layer is missing on the map, call "
                        "add_layers_to_map once (or list_user_layers) — do not re-fetch."
                    ),
                    tool_call_id=tool_call_id,
                    status="error",
                )
            ]
        }
    )
