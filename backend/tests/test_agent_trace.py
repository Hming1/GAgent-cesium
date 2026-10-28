"""Trace grouping must isolate conversations and preserve audit correlation."""

from types import SimpleNamespace
from uuid import uuid4

from services.agent_trace import build_agent_run_config


def config_for(conversation_id=None, session_id="browser", **kwargs):
    return build_agent_run_config(
        callbacks=[],
        recursion_limit=200,
        options=SimpleNamespace(
            conversation_id=conversation_id,
            model_settings=SimpleNamespace(model_provider="vllm", model_name="test-model"),
            api_key="must-not-appear-in-metadata",
        ),
        session_id=session_id,
        endpoint="/chat/stream",
        **kwargs,
    )


def test_conversations_in_one_browser_have_separate_threads():
    first = config_for("conversation-1")["metadata"]
    second = config_for("conversation-2")["metadata"]
    assert first["thread_id"] != second["thread_id"]
    assert first["application_session_id"] == second["application_session_id"]
    assert "session_id" not in first  # Avoid a conflicting LangSmith thread identifier.


def test_audit_link_and_model_metadata_exclude_request_secrets():
    run_id = uuid4()
    metadata = config_for("conversation", audit_run_id=run_id)["metadata"]
    assert metadata["agent_run_id"] == str(run_id)
    assert metadata["model_provider"] == "vllm"
    assert metadata["model_name"] == "test-model"
    assert "must-not-appear-in-metadata" not in str(metadata)


def test_missing_conversation_falls_back_to_session_but_not_unknown():
    assert config_for()["metadata"]["thread_id"] == "browser"
    assert "thread_id" not in config_for(session_id="unknown")["metadata"]
    assert "thread_id" not in config_for(session_id=None)["metadata"]
    assert "agent_run_id" not in config_for()["metadata"]
