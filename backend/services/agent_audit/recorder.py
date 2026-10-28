"""Database-backed recorder for agent run audit traces."""

import hashlib
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

from langchain.callbacks.base import BaseCallbackHandler
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.agent_audit import AgentRun, AgentRunEvent
from services.agent_audit.serializers import sanitize_for_audit, to_jsonable

logger = logging.getLogger(__name__)

AGENT_AUDIT_VERSION = "structured-trace-v1"
SessionFactory = Callable[[], AsyncSession]


def _prompt_version(model_settings: Any) -> str:
    prompt = getattr(model_settings, "system_prompt", None) if model_settings else None
    if not prompt:
        return "default"
    digest = hashlib.sha256(str(prompt).encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


def _event_run_id(kwargs: Dict[str, Any]) -> Optional[str]:
    run_id = kwargs.get("run_id")
    return str(run_id) if run_id else None


def _extract_tool_call_id(value: Any) -> Optional[str]:
    value = to_jsonable(value)
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
            found = _extract_tool_call_id(messages)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _extract_tool_call_id(item)
            if found:
                return found
    return None


def _ensure_span_id(prefix: str, preferred: Optional[str] = None) -> str:
    return preferred or f"{prefix}-{uuid.uuid4().hex}"


def _extract_token_usage(response: Any) -> Dict[str, int]:
    tokens = {"input": 0, "output": 0, "total": 0}
    candidates: List[Dict[str, Any]] = []
    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        candidates.append(llm_output.get("token_usage") or {})
    generation = _first_generation(response)
    generation_info = getattr(generation, "generation_info", None) or {}
    if isinstance(generation_info, dict):
        candidates.append(generation_info.get("token_usage") or {})
    response_json = to_jsonable(response)
    if isinstance(response_json, dict):
        json_llm_output = response_json.get("llm_output")
        if isinstance(json_llm_output, dict):
            candidates.append(json_llm_output.get("token_usage") or {})
        candidates.append(response_json.get("token_usage") or {})
        candidates.append(response_json.get("usage_metadata") or {})

    for usage in candidates:
        if not isinstance(usage, dict):
            continue
        tokens["input"] += int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        tokens["output"] += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
        tokens["total"] += int(usage.get("total_tokens") or 0)
    if tokens["total"] == 0:
        tokens["total"] = tokens["input"] + tokens["output"]
    return tokens


def _first_generation(response: Any) -> Any:
    generations = getattr(response, "generations", None)
    if generations:
        for generation_group in generations:
            if generation_group:
                return generation_group[0]
    return None


def _extract_output_message(response: Any) -> Any:
    generation = _first_generation(response)
    if generation is not None:
        message = getattr(generation, "message", None)
        if message is not None:
            return message
        text_value = getattr(generation, "text", None)
        if text_value is not None:
            return {"type": "ai", "content": text_value}
    return response


def _extract_finish_reason(response: Any) -> Optional[str]:
    generation = _first_generation(response)
    if generation is not None:
        generation_info = getattr(generation, "generation_info", None) or {}
        for key in ("finish_reason", "stop_reason"):
            if generation_info.get(key):
                return str(generation_info[key])
        message = getattr(generation, "message", None)
        metadata = getattr(message, "response_metadata", None) or {}
        for key in ("finish_reason", "stop_reason"):
            if metadata.get(key):
                return str(metadata[key])
    response_json = to_jsonable(response)
    if isinstance(response_json, dict):
        for key in ("finish_reason", "stop_reason"):
            if response_json.get(key):
                return str(response_json[key])
    return None


def _extract_tool_calls(message: Any) -> Any:
    message_json = to_jsonable(message)
    if isinstance(message_json, dict):
        return message_json.get("tool_calls") or message_json.get("additional_kwargs", {}).get(
            "tool_calls", []
        )
    return []


class AuditCallbackHandler(BaseCallbackHandler):
    """Collect sync LangChain callback events for later async persistence."""

    def __init__(
        self,
        audit_level: str = "tool",
        *,
        capture_tool_events: bool = True,
        model_settings: Any = None,
    ):
        super().__init__()
        self.audit_level = audit_level
        self.capture_tool_events = capture_tool_events
        self.model_settings = model_settings
        self.events: List[Dict[str, Any]] = []
        self._llm_starts: Dict[str, float] = {}

    def on_chat_model_start(
        self, serialized: Dict[str, Any], messages: List[List[Any]], **kwargs: Any
    ) -> None:
        self._record_llm_start(serialized, {"input_messages": messages}, kwargs)

    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any) -> None:
        self._record_llm_start(serialized, {"input_messages": [{"prompts": prompts}]}, kwargs)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self._record_llm_end(response, kwargs)

    def on_chat_model_end(self, response: Any, **kwargs: Any) -> None:
        self._record_llm_end(response, kwargs)

    def on_llm_error(self, error: Exception, **kwargs: Any) -> None:
        self._record_llm_error(error, kwargs)

    def on_chat_model_error(self, error: Exception, **kwargs: Any) -> None:
        self._record_llm_error(error, kwargs)

    def on_tool_start(self, serialized: Dict[str, Any], input_str: Any, **kwargs: Any) -> None:
        if not self.capture_tool_events or self.audit_level == "summary":
            return
        tool_call_id = _ensure_span_id(
            "tool", _extract_tool_call_id(input_str) or _event_run_id(kwargs)
        )
        self.events.append(
            {
                "event_type": "tool_start",
                "name": serialized.get("name", "unknown"),
                "input": {
                    "tool": serialized.get("name", "unknown"),
                    "tool_call_id": tool_call_id,
                    "input_json": input_str,
                },
                "payload": {"tool_call_id": tool_call_id},
            }
        )

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        if not self.capture_tool_events or self.audit_level == "summary":
            return
        tool_call_id = _ensure_span_id(
            "tool", _extract_tool_call_id(output) or _event_run_id(kwargs)
        )
        self.events.append(
            {
                "event_type": "tool_end",
                "name": kwargs.get("name"),
                "output": {
                    "tool": kwargs.get("name"),
                    "tool_call_id": tool_call_id,
                    "status": "success",
                    "output_json": output,
                },
                "payload": {"tool_call_id": tool_call_id},
            }
        )

    def on_tool_error(self, error: Exception, **kwargs: Any) -> None:
        if not self.capture_tool_events or self.audit_level == "summary":
            return
        tool_call_id = _ensure_span_id("tool", _event_run_id(kwargs))
        self.events.append(
            {
                "event_type": "tool_error",
                "name": kwargs.get("name", "unknown"),
                "output": {
                    "tool": kwargs.get("name", "unknown"),
                    "tool_call_id": tool_call_id,
                    "status": "failed",
                    "error_message": str(error),
                },
                "payload": {"tool_call_id": tool_call_id},
            }
        )

    def _record_llm_start(
        self, serialized: Dict[str, Any], input_payload: Dict[str, Any], kwargs: Dict[str, Any]
    ) -> None:
        if self.audit_level == "summary":
            return
        llm_call_id = _ensure_span_id("llm", _event_run_id(kwargs))
        self._llm_starts[llm_call_id] = time.time()
        model_name = (
            getattr(self.model_settings, "model_name", None)
            or serialized.get("name")
            or serialized.get("id")
        )
        self.events.append(
            {
                "event_type": "llm_start",
                "name": str(model_name) if model_name else "unknown",
                "input": {
                    "llm_call_id": llm_call_id,
                    "model_name": model_name,
                    "prompt_version": _prompt_version(self.model_settings),
                    **input_payload,
                },
                "payload": {"llm_call_id": llm_call_id},
            }
        )

    def _record_llm_end(self, response: Any, kwargs: Dict[str, Any]) -> None:
        if self.audit_level == "summary":
            return
        llm_call_id = _ensure_span_id("llm", _event_run_id(kwargs))
        start_time = self._llm_starts.pop(llm_call_id, None)
        latency_ms = round((time.time() - start_time) * 1000) if start_time else None
        output_message = _extract_output_message(response)
        self.events.append(
            {
                "event_type": "llm_end",
                "name": kwargs.get("name"),
                "output": {
                    "llm_call_id": llm_call_id,
                    "model_name": getattr(self.model_settings, "model_name", None),
                    "prompt_version": _prompt_version(self.model_settings),
                    "output_message": output_message,
                    "tool_calls": _extract_tool_calls(output_message),
                    "latency_ms": latency_ms,
                    "tokens": _extract_token_usage(response),
                    "finish_reason": _extract_finish_reason(response),
                    "status": "success",
                },
                "payload": {"llm_call_id": llm_call_id},
            }
        )

    def _record_llm_error(self, error: Exception, kwargs: Dict[str, Any]) -> None:
        llm_call_id = _ensure_span_id("llm", _event_run_id(kwargs))
        self._llm_starts.pop(llm_call_id, None)
        self.events.append(
            {
                "event_type": "llm_error",
                "name": kwargs.get("name"),
                "output": {
                    "llm_call_id": llm_call_id,
                    "model_name": getattr(self.model_settings, "model_name", None),
                    "prompt_version": _prompt_version(self.model_settings),
                    "status": "failed",
                    "error_message": str(error),
                },
                "payload": {"llm_call_id": llm_call_id},
            }
        )


class AgentRunRecorder:
    """Best-effort persistence wrapper for agent audit records.

    Prefer a dedicated ``session_factory`` (``AsyncSessionLocal``) instead of the
    request-scoped FastAPI session. ``/chat/stream`` may close the request session
    when streaming starts, which silently disables audit writes.
    """

    def __init__(
        self,
        db: Optional[AsyncSession],
        enabled: bool,
        audit_level: str = "tool",
        session_factory: Optional[SessionFactory] = None,
    ):
        self.db = db
        self._session_factory = session_factory
        self.enabled = bool(enabled and (session_factory is not None or db is not None))
        self.audit_level = audit_level if audit_level in {"summary", "tool", "full"} else "tool"
        self.run_id = None
        self._sequence = 0
        self._tool_error_count = 0
        self._llm_error_count = 0
        self._error_count = 0
        self._started_at = time.time()
        self._model_settings: Any = None

    @classmethod
    def from_options(cls, db: Optional[AsyncSession], options: Any) -> "AgentRunRecorder":
        model_settings = getattr(options, "model_settings", None)
        enabled = getattr(model_settings, "enable_agent_audit", True)
        env_enabled = os.getenv("ENABLE_AGENT_AUDIT")
        if env_enabled is not None:
            enabled = env_enabled.strip().lower() in {"1", "true", "yes", "on"}

        audit_level = getattr(model_settings, "agent_audit_level", "tool")
        audit_level = os.getenv("AGENT_AUDIT_LEVEL", audit_level)

        from db.session import AsyncSessionLocal

        # Always prefer an independent session factory for stream-safe writes.
        if AsyncSessionLocal is not None:
            recorder = cls(
                db=None,
                enabled=enabled,
                audit_level=audit_level,
                session_factory=AsyncSessionLocal,
            )
        else:
            recorder = cls(db=db, enabled=enabled, audit_level=audit_level)
        recorder._model_settings = model_settings
        return recorder

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        if self._session_factory is not None:
            async with self._session_factory() as session:
                yield session
            return
        if self.db is None:
            raise RuntimeError("Agent audit session is not configured")
        yield self.db

    def callback_handler(self, *, capture_tool_events: bool = True) -> AuditCallbackHandler:
        return AuditCallbackHandler(
            self.audit_level,
            capture_tool_events=capture_tool_events,
            model_settings=self._model_settings,
        )

    async def start_run(
        self,
        *,
        endpoint: str,
        request: Any,
        state: Dict[str, Any],
        options: Any,
        session_id: str,
        stream_id: Optional[str] = None,
        user_id: Optional[Any] = None,
    ) -> None:
        if not self.enabled:
            return

        try:
            model_settings = getattr(options, "model_settings", None)
            self._model_settings = model_settings
            self._started_at = time.time()
            conversation_id = getattr(options, "conversation_id", None)
            run = AgentRun(
                user_id=user_id,
                session_id=session_id,
                conversation_id=conversation_id,
                stream_id=stream_id,
                endpoint=endpoint,
                query=getattr(request, "query", None),
                status="running",
                audit_level=self.audit_level,
                model_provider=getattr(model_settings, "model_provider", None),
                model_name=getattr(model_settings, "model_name", None),
                input_messages=sanitize_for_audit(state.get("messages", [])),
                initial_state=sanitize_for_audit(state),
                options_snapshot=sanitize_for_audit(options),
            )
            async with self._session() as session:
                session.add(run)
                await session.flush()
                self.run_id = run.id
                await session.commit()
            await self.record_event(
                "run_start",
                name=endpoint,
                input_data={
                    "query": getattr(request, "query", None),
                    "input_messages": state.get("messages", []),
                },
                payload={
                    "agent_audit_version": AGENT_AUDIT_VERSION,
                    "endpoint": endpoint,
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "stream_id": stream_id,
                    "user_id": str(user_id) if user_id else None,
                    "audit_level": self.audit_level,
                    "model_provider": getattr(model_settings, "model_provider", None),
                    "model_name": getattr(model_settings, "model_name", None),
                    "max_tokens": getattr(model_settings, "max_tokens", None),
                    "prompt_version": _prompt_version(model_settings),
                    "options": options,
                },
            )
        except Exception as exc:
            logger.warning("Failed to start agent audit run: %s", exc, exc_info=True)
            self.enabled = False
            # Avoid leaking a rolled-back UUID into conversation_messages.run_id FK.
            self.run_id = None

    async def record_event(
        self,
        event_type: str,
        *,
        name: Optional[str] = None,
        input_data: Any = None,
        output_data: Any = None,
        payload: Any = None,
    ) -> None:
        if not self.enabled or self.run_id is None:
            return
        summary_events = {"run_start", "run_end", "failed", "cancelled", "error"}
        if self.audit_level == "summary" and event_type not in summary_events:
            return

        self._track_error_event(event_type, output_data)

        try:
            self._sequence += 1
            sanitized_input = sanitize_for_audit(input_data)
            sanitized_output = sanitize_for_audit(output_data)
            sanitized_payload = sanitize_for_audit(payload)
            event = AgentRunEvent(
                run_id=self.run_id,
                sequence=self._sequence,
                event_type=event_type,
                name=name,
                input=sanitized_input,
                output=sanitized_output,
                payload=sanitized_payload,
                input_json=sanitized_input,
                output_json=sanitized_output,
                payload_json=sanitized_payload,
            )
            async with self._session() as session:
                session.add(event)
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to record agent audit event: %s", exc, exc_info=True)

    async def record_events(self, events: List[Dict[str, Any]]) -> None:
        for event in events:
            await self.record_event(
                event.get("event_type", "event"),
                name=event.get("name"),
                input_data=event.get("input"),
                output_data=event.get("output"),
                payload=event.get("payload"),
            )

    async def finish_run(
        self,
        *,
        status: str,
        final_state: Optional[Dict[str, Any]] = None,
        output_messages: Any = None,
        metrics: Optional[Dict[str, Any]] = None,
        error: Any = None,
    ) -> None:
        if not self.enabled or self.run_id is None:
            return

        normalized_status = self._normalize_status(status)
        enriched_metrics = self._with_error_summary(metrics)
        duration_ms = round((time.time() - self._started_at) * 1000)

        try:
            values = {
                "status": normalized_status,
                "ended_at": text("now()"),
                "updated_at": text("now()"),
                "output_messages": sanitize_for_audit(output_messages),
                "final_state": sanitize_for_audit(final_state),
                "metrics": sanitize_for_audit(enriched_metrics),
                "error": sanitize_for_audit(error),
            }
            async with self._session() as session:
                await session.execute(
                    update(AgentRun).where(AgentRun.id == self.run_id).values(**values)
                )
                await session.commit()
            await self.record_event(
                "run_end",
                name=normalized_status,
                output_data={
                    "final_answer": output_messages,
                    "final_state": final_state,
                    "status": normalized_status,
                    "duration_ms": duration_ms,
                },
                payload={
                    "metrics": enriched_metrics,
                    "error": error,
                    "error_count": self._error_count,
                    "tool_error_count": self._tool_error_count,
                    "llm_error_count": self._llm_error_count,
                },
            )
        except Exception as exc:
            logger.warning("Failed to finish agent audit run: %s", exc, exc_info=True)

    def _track_error_event(self, event_type: str, output_data: Any) -> None:
        output_json = to_jsonable(output_data)
        status = output_json.get("status") if isinstance(output_json, dict) else None
        is_failed = status in {"failed", "error"} or event_type in {"tool_error", "llm_error"}
        if not is_failed:
            return
        self._error_count += 1
        if event_type == "tool_error":
            self._tool_error_count += 1
        elif event_type == "llm_error":
            self._llm_error_count += 1

    def _normalize_status(self, status: str) -> str:
        if status == "success" and self._error_count:
            return "partial_success"
        if status in {"error", "failed"}:
            return "failed"
        return status

    def _with_error_summary(self, metrics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        result = dict(metrics or {})
        result["error_count"] = self._error_count
        result["tool_error_count"] = self._tool_error_count
        result["llm_error_count"] = self._llm_error_count
        return result
