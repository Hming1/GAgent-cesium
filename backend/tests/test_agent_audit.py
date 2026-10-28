import uuid
from types import SimpleNamespace

import pytest

from models.settings_model import ModelSettings
from db.models.agent_audit import AgentRun, AgentRunEvent
from services.agent_audit import AgentRunRecorder
from services.agent_audit.recorder import AuditCallbackHandler
from services.agent_audit.serializers import sanitize_for_audit


def test_model_settings_agent_audit_defaults():
    settings = ModelSettings(
        model_provider="openai",
        model_name="gpt-4o-mini",
        max_tokens=1000,
    )

    assert settings.enable_agent_audit is True
    assert settings.agent_audit_level == "tool"


def test_sanitize_for_audit_redacts_secrets_and_truncates_geometries():
    payload = {
        "api_key": "secret",
        "headers": {"Authorization": "Bearer secret"},
        "geojson": {
            "type": "FeatureCollection",
            "features": [{"type": "Feature"} for _ in range(3)],
        },
    }

    sanitized = sanitize_for_audit(payload)

    assert sanitized["api_key"] == "[redacted]"
    assert sanitized["headers"] == "[redacted]"
    assert sanitized["geojson"]["features"]["truncated"] is True
    assert sanitized["geojson"]["features"]["item_count"] == 3


@pytest.mark.asyncio
async def test_disabled_recorder_is_noop():
    recorder = AgentRunRecorder(db=None, enabled=False)

    await recorder.start_run(
        endpoint="/chat",
        request=object(),
        state={"messages": []},
        options=object(),
        session_id="session",
    )
    await recorder.record_event("tool_start", name="tool")
    await recorder.finish_run(status="success")

    assert recorder.enabled is False
    assert recorder.run_id is None


def test_from_options_prefers_independent_session_factory(monkeypatch):
    fake_factory = object()
    monkeypatch.setattr(
        "db.session.AsyncSessionLocal",
        fake_factory,
    )
    options = SimpleNamespace(model_settings=_settings())
    recorder = AgentRunRecorder.from_options(db=None, options=options)

    assert recorder.enabled is True
    assert recorder._session_factory is fake_factory
    assert recorder.db is None


def test_tool_output_data_extracts_command_tool_message_error():
    from api.nalamap import _build_tool_output_data
    from langchain_core.messages import ToolMessage

    output = {
        "messages": [
            ToolMessage(
                content="Error: broken layer",
                name="attribute_tool2",
                tool_call_id="tool-123",
                status="error",
            )
        ]
    }

    result = _build_tool_output_data("attribute_tool2", output)

    assert result["tool"] == "attribute_tool2"
    assert result["tool_call_id"] == "tool-123"
    assert result["status"] == "failed"
    assert result["error_message"] == "Error: broken layer"
    assert result["is_state_update"] is True
    assert result["tool_message"]["content"] == "Error: broken layer"


class _FakeAuditDB:
    def __init__(self):
        self.items = []
        self.commits = 0
        self.executed = []

    def add(self, item):
        self.items.append(item)

    async def flush(self):
        for item in self.items:
            if isinstance(item, AgentRun) and item.id is None:
                item.id = uuid.uuid4()

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def execute(self, statement):
        self.executed.append(statement)


def _settings():
    return ModelSettings(
        model_provider="openai",
        model_name="gpt-4o-mini",
        max_tokens=1000,
        system_prompt="trace me",
    )


@pytest.mark.asyncio
async def test_recorder_writes_run_events_json_fields_and_partial_success():
    db = _FakeAuditDB()
    options = SimpleNamespace(
        model_settings=_settings(),
        conversation_id="conversation-1",
        session_id="session-1",
    )
    # Inject the fake session directly; from_options prefers AsyncSessionLocal.
    recorder = AgentRunRecorder(db=db, enabled=True, audit_level="tool")
    recorder._model_settings = _settings()

    await recorder.start_run(
        endpoint="/chat",
        request=SimpleNamespace(query="list fields"),
        state={"messages": []},
        options=options,
        session_id="session-1",
        stream_id="stream-1",
    )
    await recorder.record_event(
        "tool_error",
        name="attribute_tool2",
        output_data={
            "tool": "attribute_tool2",
            "tool_call_id": "tool-1",
            "status": "failed",
            "error_message": "broken",
        },
        payload={"tool_call_id": "tool-1"},
    )
    await recorder.finish_run(
        status="success",
        final_state={"messages": []},
        output_messages=[{"type": "ai", "content": "done"}],
        metrics={"total_time": 1.0},
    )

    events = [item for item in db.items if isinstance(item, AgentRunEvent)]
    assert [event.event_type for event in events] == ["run_start", "tool_error", "run_end"]
    assert isinstance(events[0].input_json, dict)
    assert isinstance(events[0].payload_json, dict)
    assert events[1].output_json["tool_call_id"] == "tool-1"
    assert events[1].output_json["status"] == "failed"
    assert events[2].output_json["status"] == "partial_success"
    assert events[2].payload_json["error_count"] == 1
    assert events[2].payload_json["tool_error_count"] == 1


def test_audit_callback_records_structured_llm_events():
    from langchain_core.messages import AIMessage, HumanMessage

    handler = AuditCallbackHandler(audit_level="tool", model_settings=_settings())
    handler.on_chat_model_start({}, [[HumanMessage(content="hello")]], run_id="llm-1")
    response = SimpleNamespace(
        llm_output={
            "token_usage": {
                "prompt_tokens": 7,
                "completion_tokens": 5,
                "total_tokens": 12,
            }
        },
        generations=[
            [
                SimpleNamespace(
                    message=AIMessage(
                        content="I will call a tool",
                        tool_calls=[{"name": "list_fields", "args": {}, "id": "tool-1"}],
                    ),
                    generation_info={"finish_reason": "tool_calls"},
                )
            ]
        ],
    )
    handler.on_chat_model_end(response, run_id="llm-1")

    assert [event["event_type"] for event in handler.events] == ["llm_start", "llm_end"]
    llm_end = handler.events[1]["output"]
    assert llm_end["llm_call_id"] == "llm-1"
    assert llm_end["model_name"] == "gpt-4o-mini"
    assert llm_end["tokens"] == {"input": 7, "output": 5, "total": 12}
    assert llm_end["finish_reason"] == "tool_calls"
    assert "tool_calls" in llm_end
    assert llm_end["latency_ms"] is not None
