"""Serialization and sanitization helpers for agent audit records."""

import json
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "headers",
    "password",
    "secret",
    "token",
}
MAX_STRING_LENGTH = 20000
MAX_LIST_ITEMS = 100
MAX_DICT_ITEMS = 200


def to_jsonable(obj: Any) -> Any:
    """Convert common project objects to JSON-serializable values."""
    if obj is None:
        return None
    if isinstance(obj, HumanMessage):
        return {"type": "human", "content": obj.content}
    if isinstance(obj, AIMessage):
        result = {"type": "ai", "content": obj.content}
        if getattr(obj, "additional_kwargs", None):
            result["additional_kwargs"] = to_jsonable(obj.additional_kwargs)
        if getattr(obj, "tool_calls", None):
            result["tool_calls"] = to_jsonable(obj.tool_calls)
        if getattr(obj, "response_metadata", None):
            result["response_metadata"] = to_jsonable(obj.response_metadata)
        return result
    if isinstance(obj, SystemMessage):
        return {"type": "system", "content": obj.content}
    if isinstance(obj, (ToolMessage, FunctionMessage)):
        result = {"type": "tool", "content": obj.content}
        if getattr(obj, "tool_call_id", None):
            result["tool_call_id"] = obj.tool_call_id
        if getattr(obj, "name", None):
            result["name"] = obj.name
        return result
    if isinstance(obj, BaseMessage):
        return {"type": "message", "content": str(obj.content)}
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            return str(obj)
    if isinstance(obj, dict):
        return {str(key): to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(item) for item in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj

    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def sanitize_for_audit(obj: Any, max_depth: int = 8) -> Any:
    """Redact sensitive values and cap large payloads before persistence."""
    return _sanitize(to_jsonable(obj), depth=0, max_depth=max_depth)


def _sanitize(obj: Any, depth: int, max_depth: int) -> Any:
    if depth > max_depth:
        return {"truncated": True, "reason": "max_depth"}

    if obj is None or isinstance(obj, (int, float, bool)):
        return obj

    if isinstance(obj, str):
        if len(obj) > MAX_STRING_LENGTH:
            return obj[:MAX_STRING_LENGTH] + "...[truncated]"
        return obj

    if isinstance(obj, list):
        items = [_sanitize(item, depth + 1, max_depth) for item in obj[:MAX_LIST_ITEMS]]
        if len(obj) > MAX_LIST_ITEMS:
            items.append({"truncated": True, "remaining_items": len(obj) - MAX_LIST_ITEMS})
        return items

    if isinstance(obj, dict):
        sanitized = {}
        for index, (key, value) in enumerate(obj.items()):
            if index >= MAX_DICT_ITEMS:
                sanitized["__truncated__"] = {
                    "remaining_items": len(obj) - MAX_DICT_ITEMS,
                }
                break
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS:
                sanitized[key_text] = "[redacted]"
            elif key_text in {"features", "coordinates"} and isinstance(value, list):
                sanitized[key_text] = {
                    "truncated": True,
                    "item_count": len(value),
                    "reason": "large_geospatial_payload",
                }
            else:
                sanitized[key_text] = _sanitize(value, depth + 1, max_depth)
        return sanitized

    return str(obj)
