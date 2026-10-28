import json
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from httpx_sse import aconnect_sse
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from api import nalamap
from models.messages.chat_messages import GeoAgentRequest
from models.settings_model import ModelSettings
from services import single_agent
from services.tools.geostate_management import create_execution_plan


def _settings_payload(plan_mode: bool = True):
    return {
        "search_portals": [],
        "geoserver_backends": [],
        "mcp_servers": [],
        "model_settings": {
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "max_tokens": 4096,
            "plan_mode": plan_mode,
        },
        "tools": [],
        "tool_options": {},
        "session_id": "test-plan-session",
    }


def _pending_plan():
    return {
        "title": "Test execution plan",
        "steps": [
            {
                "action": "List current layers",
                "tool": "list_user_layers",
            }
        ],
        "summary": "Return current layers",
        "status": "pending",
        "step_count": 1,
    }


def _plan_with_status(status: str):
    plan = _pending_plan()
    plan["status"] = status
    return plan


def test_request_plan_action_honors_confirmed_plan_status():
    request = GeoAgentRequest(
        query="continue with the approved workflow",
        execution_plan=_plan_with_status("confirmed"),
    )

    assert nalamap._get_request_plan_action(request) == "confirm"


def test_confirmed_response_does_not_restore_pending_plan():
    response_plan = nalamap._execution_plan_for_response(
        _pending_plan(),
        _plan_with_status("confirmed"),
        "confirm",
    )

    assert response_plan["status"] == "confirmed"


def test_confirmed_plan_filters_tools_to_planned_tool_names():
    tools = {
        "attribute_tool2": SimpleNamespace(name="attribute_tool2"),
        "geoprocess": SimpleNamespace(name="geoprocess_tool"),
        "search_metadata": SimpleNamespace(name="metadata_search"),
        "list_user_layers": SimpleNamespace(name="list_user_layers"),
    }

    filtered = single_agent._filter_tools_for_confirmed_plan(
        tools,
        ["attribute_tool2", "geoprocess_tool"],
    )

    assert set(filtered) == {"attribute_tool2", "geoprocess"}


def test_confirmed_plan_filters_display_tool_names():
    tools = {
        "geoprocess": SimpleNamespace(name="geoprocess_tool"),
        "search_metadata": SimpleNamespace(name="metadata_search"),
        "list_user_layers": SimpleNamespace(name="list_user_layers"),
    }

    filtered = single_agent._filter_tools_for_confirmed_plan(
        tools,
        ["Geoprocess Tool", "Metadata Search"],
    )

    assert set(filtered) == {"geoprocess", "search_metadata"}


class _PlanTestModel(FakeMessagesListChatModel):
    bound_tool_names: list[str] = []
    binding_options: dict = {}

    def bind_tools(self, tools, **kwargs):
        self.bound_tool_names = [item.name for item in tools]
        self.binding_options.update(kwargs)
        return self


def _plan_call():
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "create_execution_plan",
                "id": "new-plan",
                "args": {
                    "title": "New request plan",
                    "steps": [{"action": "List layers", "tool": "list_user_layers"}],
                    "summary": "Show current layers",
                },
            }
        ],
    )


def _business_call():
    return AIMessage(
        content="",
        tool_calls=[{"name": "list_user_layers", "id": "execute", "args": {}}],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_history", [False, True])
@pytest.mark.parametrize("dynamic_tools", [False, True])
async def test_plan_mode_blocks_business_tools_and_stops_after_plan(
    monkeypatch, with_history, dynamic_tools
):
    executed = []

    @tool
    def list_user_layers() -> str:
        """List current layers."""
        executed.append(True)
        return "Current layers"

    # Simulate a model following earlier execution history instead of the plan
    # instruction, then attempting to execute again after producing a plan.
    model = _PlanTestModel(
        responses=[_business_call(), _plan_call(), _business_call(), AIMessage(content="Done")]
    )

    @tool
    def external_analysis() -> str:
        """Analyze using an external MCP service."""
        executed.append("mcp")
        return "External result"

    model.responses[0].tool_calls.append(
        {"name": "external_analysis", "id": "external", "args": {}, "type": "tool_call"}
    )

    async def fake_load_mcp_tools(*args, **kwargs):
        return [external_analysis]

    monkeypatch.setattr("services.mcp.integration.load_mcp_tools", fake_load_mcp_tools)
    monkeypatch.setattr(
        "services.ai.llm_config.get_llm_for_provider",
        lambda **kwargs: (model, SimpleNamespace(supports_parallel_tool_calls=True)),
    )
    monkeypatch.setattr(
        single_agent,
        "create_configured_tools",
        lambda *args: {
            "create_execution_plan": create_execution_plan,
            "list_user_layers": list_user_layers,
        },
    )

    class Selector:
        async def select_tools(self, query, tools):
            # The selector can omit the planning tool even in plan mode.
            return [list_user_layers]

    monkeypatch.setattr("services.tool_selector.create_tool_selector", lambda **kwargs: Selector())
    monkeypatch.setattr("services.ai.llm_config.get_embeddings", lambda: None, raising=False)
    history = (
        [
            HumanMessage(content="List layers directly"),
            AIMessage(
                content="",
                tool_calls=[{"name": "list_user_layers", "id": "old-call", "args": {}}],
            ),
            ToolMessage(content="Old layers", tool_call_id="old-call"),
            AIMessage(content="The previous task is complete."),
            HumanMessage(content="确认"),
            AIMessage(content="The previous plan has been executed."),
        ]
        if with_history
        else []
    )
    agent, _ = await single_agent.create_geo_agent(
        model_settings=ModelSettings(
            **{
                **_settings_payload()["model_settings"],
                "enable_dynamic_tools": dynamic_tools,
            }
        ),
        query="Plan a new layer analysis",
        enable_parallel_tools=True,
        mcp_servers=[SimpleNamespace(url="https://test.invalid/mcp")],
    )
    result = await agent.ainvoke(
        {
            "messages": history + [HumanMessage(content="Plan a new layer analysis")],
            "execution_plan": None,
            "options": _settings_payload(),
            "remaining_steps": 10,
        }
    )

    assert executed == []
    assert result.get("execution_plan") is not None, repr(result["messages"])
    assert result["execution_plan"]["status"] == "pending"
    assert result["execution_plan"]["title"] == "New request plan"
    assert model.bound_tool_names == ["create_execution_plan"]
    assert model.binding_options["tool_choice"] == "create_execution_plan"
    assert model.binding_options["parallel_tool_calls"] is False
    assert model.i == 2  # No model/tool execution after generating the plan.
    assert create_execution_plan.return_direct is False  # Do not mutate registry tools.


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [False, True])
async def test_normal_and_confirmed_requests_still_execute_business_tools(monkeypatch, confirmed):
    executed = []

    @tool
    def list_user_layers() -> str:
        """List current layers."""
        executed.append(True)
        return "Current layers"

    model = _PlanTestModel(responses=[_business_call(), AIMessage(content="Done")])
    monkeypatch.setattr(
        "services.ai.llm_config.get_llm_for_provider",
        lambda **kwargs: (model, SimpleNamespace(supports_parallel_tool_calls=False)),
    )
    monkeypatch.setattr(
        single_agent,
        "create_configured_tools",
        lambda *args: {
            "create_execution_plan": create_execution_plan,
            "list_user_layers": list_user_layers,
        },
    )
    agent, _ = await single_agent.create_geo_agent(
        model_settings=ModelSettings(**_settings_payload(confirmed)["model_settings"]),
        suppress_plan_tool=confirmed,
        confirmed_plan_tools=["list_user_layers"] if confirmed else None,
    )
    result = await agent.ainvoke({"messages": [HumanMessage(content="List layers")]})
    assert executed == [True]
    assert result["messages"][-1].content == "Done"
    assert "create_execution_plan" not in model.bound_tool_names
    assert "tool_choice" not in model.binding_options


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_real_graph_returns_pending_plan_after_old_confirmation(
    monkeypatch, async_client: AsyncClient, streaming
):
    model = _PlanTestModel(responses=[_plan_call(), AIMessage(content="Must not continue")])
    monkeypatch.setattr(
        "services.ai.llm_config.get_llm_for_provider",
        lambda **kwargs: (model, SimpleNamespace(supports_parallel_tool_calls=False)),
    )
    options = _settings_payload()
    options["model_settings"].update(
        enable_memory=False, enable_agent_audit=False, message_management_mode="prune"
    )
    payload = {
        "query": "Plan a new analysis",
        "messages": [
            {"type": "human", "content": "确认"},
            {"type": "ai", "content": "The old plan is complete."},
        ],
        "options": options,
    }
    if streaming:
        events = []
        result = None
        async with aconnect_sse(
            async_client, "POST", "/api/chat/stream", json=payload
        ) as event_source:
            async for sse in event_source.aiter_sse():
                events.append(sse.event)
                if sse.event == "result":
                    result = json.loads(sse.data)
        assert "plan_created" in events
        assert "error" not in events
    else:
        response = await async_client.post("/api/chat", json=payload)
        assert response.status_code == 200
        result = response.json()
    assert result["execution_plan"]["status"] == "pending"
    assert result["execution_plan"]["title"] == "New request plan"
    assert model.i == 1


class _Metrics:
    metrics = {"message_count_before": 0}

    def record(self, key, value):
        self.metrics[key] = value


class _FakeAgent:
    pass


class _StreamingFakeAgent:
    async def astream_events(self, state, version="v2", config=None):
        yield {
            "event": "on_chain_end",
            "name": "GeoAgent",
            "data": {
                "output": {
                    "messages": [AIMessage(content="Executed the confirmed plan.")],
                    "results_title": "",
                    "geodata_results": [],
                    "geodata_layers": [],
                    "execution_plan": _pending_plan(),
                }
            },
        }


class _Perf:
    def get_metrics(self):
        return {"token_usage": {"total": 0}}


@pytest.mark.asyncio
async def test_prepare_chat_context_includes_execution_plan(monkeypatch):
    captured = {}

    async def fake_create_geo_agent(**kwargs):
        captured.update(kwargs)
        return _FakeAgent(), object()

    async def fake_prepare_messages(**kwargs):
        return kwargs["messages"]

    monkeypatch.setattr(
        "services.single_agent.create_geo_agent",
        fake_create_geo_agent,
    )
    monkeypatch.setattr(
        "services.single_agent.prepare_messages",
        fake_prepare_messages,
    )

    request = GeoAgentRequest(
        messages=[],
        query="confirm",
        geodata_last_results=[],
        geodata_layers=[],
        execution_plan=_pending_plan(),
        options=_settings_payload(),
    )
    raw_request = SimpleNamespace(cookies={})

    state, *_ = await nalamap._prepare_chat_context(
        request,
        raw_request,
        _Metrics(),
        db=None,
        suppress_plan_tool=True,
    )

    assert state["execution_plan"]["status"] == "confirmed"
    assert captured["suppress_plan_tool"] is True
    assert captured["confirmed_plan_tools"] == ["list_user_layers"]


@pytest.mark.asyncio
async def test_chat_confirm_suppresses_plan_tool(monkeypatch):
    captured = {}

    async def fake_prepare_chat_context(
        request,
        raw_request,
        metrics,
        db=None,
        suppress_plan_tool=False,
    ):
        captured["execution_plan"] = request.execution_plan
        captured["suppress_plan_tool"] = suppress_plan_tool
        state = {
            "messages": [],
            "geodata_layers": [],
            "execution_plan": request.execution_plan,
        }
        return (
            state,
            _FakeAgent(),
            SimpleNamespace(model_settings=SimpleNamespace()),
            _Perf(),
            "s",
            "s",
        )

    def fake_invoke(state, debug=False, config=None):
        return {
            "messages": [AIMessage(content="Executed the confirmed plan.")],
            "results_title": "",
            "geodata_results": [],
            "geodata_layers": [],
            "execution_plan": _pending_plan(),
            "options": {},
        }

    monkeypatch.setattr(nalamap, "_prepare_chat_context", fake_prepare_chat_context)
    _FakeAgent.invoke = fake_invoke

    request = GeoAgentRequest(
        messages=[],
        query="confirm",
        geodata_last_results=[],
        geodata_layers=[],
        execution_plan=_pending_plan(),
        options=_settings_payload(),
    )
    raw_request = SimpleNamespace(cookies={})

    response = await nalamap.ask_nalamap_agent(request, raw_request, db=None)

    assert captured["suppress_plan_tool"] is True
    assert captured["execution_plan"]["status"] == "confirmed"
    assert response.execution_plan["status"] == "confirmed"


@pytest.mark.asyncio
async def test_stream_confirm_does_not_reemit_pending_plan(
    monkeypatch,
    async_client: AsyncClient,
):
    captured = {}

    async def fake_prepare_chat_context(
        request,
        raw_request,
        metrics,
        db=None,
        suppress_plan_tool=False,
    ):
        captured["execution_plan"] = request.execution_plan
        captured["suppress_plan_tool"] = suppress_plan_tool
        state = {
            "messages": [],
            "geodata_layers": [],
            "execution_plan": request.execution_plan,
        }
        return (
            state,
            _StreamingFakeAgent(),
            SimpleNamespace(model_settings=SimpleNamespace()),
            _Perf(),
            "s",
            "s",
        )

    monkeypatch.setattr(nalamap, "_prepare_chat_context", fake_prepare_chat_context)

    payload = {
        "messages": [],
        "query": "continue with the approved workflow",
        "geodata_last_results": [],
        "geodata_layers": [],
        "execution_plan": _plan_with_status("confirmed"),
        "options": _settings_payload(),
    }

    event_types = []
    result_data = None
    async with aconnect_sse(
        async_client,
        "POST",
        "/api/chat/stream",
        json=payload,
        timeout=30.0,
    ) as event_source:
        async for sse in event_source.aiter_sse():
            event_types.append(sse.event)
            if sse.event == "result":
                result_data = json.loads(sse.data)
            if sse.event == "done":
                break

    assert captured["suppress_plan_tool"] is True
    assert captured["execution_plan"]["status"] == "confirmed"
    assert "plan_created" not in event_types
    assert result_data is not None
    assert result_data["execution_plan"]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_chat_pending_plan_without_confirmation_skips_agent(monkeypatch):
    async def fail_prepare_chat_context(*args, **kwargs):
        raise AssertionError("Agent should not run before a pending plan is confirmed")

    monkeypatch.setattr(nalamap, "_prepare_chat_context", fail_prepare_chat_context)

    request = GeoAgentRequest(
        messages=[],
        query="缁х画鍒嗘瀽",
        geodata_last_results=[],
        geodata_layers=[],
        execution_plan=_pending_plan(),
        options=_settings_payload(),
    )
    raw_request = SimpleNamespace(cookies={})

    response = await nalamap.ask_nalamap_agent(request, raw_request, db=None)

    assert response.execution_plan["status"] == "pending"
    assert "尚未确认" in response.messages[-1].content


@pytest.mark.asyncio
async def test_stream_pending_plan_without_confirmation_skips_agent(
    monkeypatch,
    async_client: AsyncClient,
):
    async def fail_prepare_chat_context(*args, **kwargs):
        raise AssertionError("Agent should not run before a pending plan is confirmed")

    monkeypatch.setattr(nalamap, "_prepare_chat_context", fail_prepare_chat_context)

    payload = {
        "messages": [],
        "query": "缁х画鍒嗘瀽",
        "geodata_last_results": [],
        "geodata_layers": [],
        "execution_plan": _pending_plan(),
        "options": _settings_payload(),
    }

    event_types = []
    result_data = None
    async with aconnect_sse(
        async_client,
        "POST",
        "/api/chat/stream",
        json=payload,
        timeout=30.0,
    ) as event_source:
        async for sse in event_source.aiter_sse():
            event_types.append(sse.event)
            if sse.event == "result":
                result_data = json.loads(sse.data)
            if sse.event == "done":
                break

    assert "tool_start" not in event_types
    assert "plan_created" not in event_types
    assert result_data is not None
    assert result_data["execution_plan"]["status"] == "pending"
    assert "尚未确认" in result_data["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_stream_cancel_pending_plan_skips_agent(async_client: AsyncClient):
    payload = {
        "messages": [],
        "query": "cancel",
        "geodata_last_results": [],
        "geodata_layers": [],
        "execution_plan": _pending_plan(),
        "options": _settings_payload(),
    }

    result_data = None
    async with aconnect_sse(
        async_client,
        "POST",
        "/api/chat/stream",
        json=payload,
        timeout=30.0,
    ) as event_source:
        async for sse in event_source.aiter_sse():
            if sse.event == "result":
                result_data = json.loads(sse.data)
            if sse.event == "done":
                break

    assert result_data is not None
    assert result_data["execution_plan"]["status"] == "cancelled"
    assert result_data["messages"][-1]["content"]
