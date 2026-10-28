"""Regression coverage for tool history carried into a follow-up request."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx_sse import aconnect_sse
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from api.nalamap import _drop_orphan_tool_calls, make_json_serializable, normalize_messages
from models.messages.chat_messages import GeoAgentRequest
from services.conversation.store import filter_duplicate_messages


def tool_turn():
    return [
        HumanMessage(content="Find schools in Guangzhou"),
        AIMessage(
            content="",
            tool_calls=[{"id": "schools-1", "name": "find_schools", "args": {"city": "Guangzhou"}}],
            additional_kwargs={"reasoning_content": "Search the requested city"},
        ),
        ToolMessage(content="224 schools", tool_call_id="schools-1", name="find_schools"),
        AIMessage(content="Guangzhou schools are on the map"),
        HumanMessage(content="Shenzhen too"),
    ]


def test_serialized_history_retains_canonical_calls_and_tool_results():
    request = GeoAgentRequest(messages=make_json_serializable(tool_turn()))
    messages = normalize_messages(request.messages)
    assert messages[1].tool_calls == tool_turn()[1].tool_calls
    assert messages[1].additional_kwargs["reasoning_content"] == "Search the requested city"
    assert isinstance(messages[2], ToolMessage)
    assert messages[2].tool_call_id == "schools-1"
    assert [m.content for m in messages if isinstance(m, HumanMessage)] == [
        "Find schools in Guangzhou",
        "Shenzhen too",
    ]


def test_legacy_function_calls_roundtrip():
    history = make_json_serializable(tool_turn())
    history[1].pop("tool_calls")
    history[1]["additional_kwargs"]["tool_calls"] = [
        {
            "id": "schools-1",
            "type": "function",
            "function": {"name": "find_schools", "arguments": '{"city":"Guangzhou"}'},
        }
    ]
    messages = normalize_messages(GeoAgentRequest(messages=history).messages)
    assert messages[1].tool_calls == tool_turn()[1].tool_calls


@pytest.mark.parametrize("with_id", [False, True])
def test_orphan_tool_results_never_become_user_instructions(with_id):
    result = {"type": "tool", "content": "Old tool output"}
    if with_id:
        result["tool_call_id"] = "lost-call"
    messages = normalize_messages(
        GeoAgentRequest(messages=[result, {"type": "human", "content": "Shenzhen too"}]).messages
    )
    assert [m.content for m in messages if isinstance(m, HumanMessage)] == ["Shenzhen too"]
    assert not any(isinstance(m, ToolMessage) for m in messages)


def test_repeated_empty_calls_are_persisted_as_distinct_executions():
    first = tool_turn()[1]
    second = first.model_copy(
        update={
            "tool_calls": [
                {
                    "id": "schools-2",
                    "name": "find_schools",
                    "args": {"city": "Shenzhen"},
                    "type": "tool_call",
                }
            ]
        }
    )
    kept = filter_duplicate_messages([first, second, first], set())
    assert [m.tool_calls[0]["id"] for m in kept] == ["schools-1", "schools-2"]


def test_truncated_history_drops_unmatched_results_and_legacy_calls():
    messages = tool_turn()
    assert _drop_orphan_tool_calls(messages[2:]) == messages[3:]
    call = messages[1].model_copy(
        update={
            "additional_kwargs": {
                "tool_calls": [{"id": "schools-1", "function": {"name": "find_schools"}}],
                "reasoning_content": "Preserve provider metadata",
            },
            "content": "Searching",
        }
    )
    repaired = _drop_orphan_tool_calls([call, messages[-1]])
    assert repaired[0].tool_calls == []
    assert "tool_calls" not in repaired[0].additional_kwargs
    assert repaired[0].additional_kwargs["reasoning_content"] == "Preserve provider metadata"


def test_partial_parallel_results_keep_only_answered_calls_once():
    call = AIMessage(
        content="Checking",
        tool_calls=[
            {"id": "answered", "name": "find_schools", "args": {}},
            {"id": "missing", "name": "find_schools", "args": {}},
        ],
    )
    result = ToolMessage(content="Service failed", tool_call_id="answered", status="error")
    messages = normalize_messages(
        GeoAgentRequest(
            messages=make_json_serializable(
                [call, result, result, HumanMessage(content="Try Shenzhen")]
            )
        ).messages
    )
    assert [tc["id"] for tc in messages[0].tool_calls] == ["answered"]
    assert len(messages) == 3
    assert messages[1].status == "error"


def test_tool_results_cannot_pair_across_user_turns():
    turn = tool_turn()
    repaired = _drop_orphan_tool_calls([turn[1], turn[-1], turn[2]])
    assert repaired == [turn[-1]]


class FollowupModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        # Match the deployed Qwen chat template, which only accepts a system
        # message at index zero (not several consecutive system messages).
        assert all(
            not isinstance(msg, SystemMessage) for msg in messages[1:]
        ), "System message must be at the beginning."
        return super()._generate(messages, *args, **kwargs)


class TraceMetadataRecorder(BaseCallbackHandler):
    def __init__(self):
        self.calls = []

    def on_chat_model_start(self, serialized, messages, *, metadata=None, **kwargs):
        self.calls.append(metadata or {})


@pytest.mark.asyncio
@pytest.mark.parametrize("block_content", [False, True])
async def test_prompt_preserves_memory_and_summary_in_one_system_message(
    monkeypatch, block_content
):
    from models.settings_model import ModelSettings
    from services import single_agent

    captured = {}
    model = FollowupModel(responses=[AIMessage(content="Done")])
    monkeypatch.setattr(
        "services.ai.llm_config.get_llm_for_provider",
        lambda **kwargs: (model, SimpleNamespace(supports_parallel_tool_calls=False)),
    )
    monkeypatch.setattr(single_agent, "create_configured_tools", lambda *args: {})
    monkeypatch.setattr(
        single_agent, "create_react_agent", lambda **kwargs: captured.update(kwargs)
    )
    await single_agent.create_geo_agent(
        model_settings=ModelSettings(
            model_provider="openai",
            model_name="gpt-4o-mini",
            max_tokens=4096,
            system_prompt="Base instructions",
        )
    )
    memory = "Remember public schools"
    if block_content:
        memory = [{"type": "text", "text": memory}]
    messages = [
        SystemMessage(content=memory),
        HumanMessage(content="Shanghai too"),
        SystemMessage(content="Conversation summary: Guangzhou and Shenzhen done"),
        HumanMessage(content=""),
    ]
    prompt = captured["prompt"]({"messages": messages})
    assert len(prompt) == 2
    assert isinstance(prompt[0], SystemMessage)
    assert prompt[1] is messages[1]
    content = prompt[0].content
    text = content if isinstance(content, str) else "\n".join(block["text"] for block in content)
    for expected in [
        "Base instructions",
        "<system_state>",
        "Remember public schools",
        "Conversation summary:",
    ]:
        assert expected in text
    assert messages[0].content == memory  # prompt assembly does not mutate stored history


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("management_mode", ["prune", "summarize"])
async def test_four_cities_execute_tools_through_real_graph(
    monkeypatch, async_client, streaming, management_mode
):
    import json

    from services import single_agent

    executed = []

    @tool
    def find_schools(city: str) -> str:
        """Find schools in a city."""
        executed.append(city)
        return f"Schools in {city}"

    cities = ["Guangzhou", "Shenzhen", "Shanghai", "Beijing"]
    responses = []
    for index, city in enumerate(cities):
        if management_mode == "summarize" and index >= 2:
            responses.append(AIMessage(content="Previous cities have schools on the map."))
        responses.extend(
            [
                AIMessage(
                    content="",
                    tool_calls=[{"id": city, "name": "find_schools", "args": {"city": city}}],
                ),
                AIMessage(content=f"{city} done"),
            ]
        )
    trace_metadata = TraceMetadataRecorder()
    model = FollowupModel(responses=responses, callbacks=[trace_metadata])
    monkeypatch.setattr(single_agent, "conversation_managers", {})
    monkeypatch.setattr(
        "services.ai.llm_config.get_llm_for_provider",
        lambda **kwargs: (model, SimpleNamespace(supports_parallel_tool_calls=False)),
    )
    monkeypatch.setattr(
        single_agent, "create_configured_tools", lambda *args: {"find_schools": find_schools}
    )
    monkeypatch.setattr("api.nalamap._persist_conversation_turn", AsyncMock())
    options = {
        "model_settings": {
            "model_provider": "openai",
            "model_name": "gpt-4o-mini",
            "max_tokens": 4096,
            "enable_memory": False,
            "enable_agent_audit": False,
            "message_management_mode": management_mode,
            "message_window_size": 4,
        },
        "search_portals": [],
        "geoserver_backends": [],
        "mcp_servers": [],
        "tools": [],
        "tool_options": {},
        "session_id": "history-regression",
        "conversation_id": "history-conversation",
    }
    history = []
    for city in cities:
        query = f"Find {city} schools"
        payload = {
            "query": query,
            "messages": history,
            "options": options,
            "geodata_layers": [],
            "geodata_last_results": [],
        }
        if streaming:
            events = []
            async with aconnect_sse(
                async_client, "POST", "/api/chat/stream", json=payload
            ) as source:
                async for event in source.aiter_sse():
                    events.append(event.event)
                    if event.event == "result":
                        result = json.loads(event.data)
            assert "error" not in events
            assert "tool_start" in events
        else:
            response = await async_client.post("/api/chat", json=payload)
            assert response.status_code == 200
            result = response.json()
        history = result["messages"]
        assert history[-1]["content"] == f"{city} done"
    assert executed == cities
    assert len(history) == 16  # UI history survives pruning and repeated summaries
    restored = normalize_messages(GeoAgentRequest(messages=history).messages)
    assert [m.tool_call_id for m in restored if isinstance(m, ToolMessage)] == cities
    assert restored[-1].content == "Beijing done"
    agent_calls = [m for m in trace_metadata.calls if m.get("application") == "nalamap"]
    assert len(agent_calls) >= 8  # Two model calls for each of the four user turns.
    for metadata in agent_calls:
        assert metadata["thread_id"] == "history-conversation"
        assert metadata["application_session_id"] == "history-regression"
        assert metadata["endpoint"] == ("/chat/stream" if streaming else "/chat")
