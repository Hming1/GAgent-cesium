"""Shared LangChain trace metadata for chat and streaming agent runs."""

from typing import Any, Optional, Sequence

from langchain_core.runnables import RunnableConfig


def build_agent_run_config(
    *,
    callbacks: Sequence[Any],
    recursion_limit: int,
    options: Any,
    session_id: Optional[str],
    endpoint: str,
    audit_run_id: Any = None,
) -> RunnableConfig:
    """Link LangSmith threads to conversations without copying request secrets.

    A browser session can contain multiple conversations. Use conversation_id
    for LangSmith's thread grouping and retain the browser session separately.
    LangChain propagates this metadata to model and tool child runs.
    """
    conversation_id = getattr(options, "conversation_id", None)
    thread_id = conversation_id or (session_id if session_id != "unknown" else None)
    model_settings = getattr(options, "model_settings", None)
    metadata = {"application": "nalamap", "endpoint": endpoint}
    optional = {
        "thread_id": thread_id,
        "conversation_id": conversation_id,
        "application_session_id": session_id if session_id != "unknown" else None,
        "agent_run_id": audit_run_id,
        "model_provider": getattr(model_settings, "model_provider", None),
        "model_name": getattr(model_settings, "model_name", None),
    }
    metadata.update({key: str(value) for key, value in optional.items() if value})
    return {
        "callbacks": list(callbacks),
        "recursion_limit": recursion_limit,
        "run_name": "GeoAgent",
        "tags": ["nalamap", "chat-stream" if endpoint == "/chat/stream" else "chat"],
        "metadata": metadata,
    }
