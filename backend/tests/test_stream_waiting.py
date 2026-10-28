"""Slow model events must survive cancellation polling and report failures."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from api import nalamap
from models.settings_model import SettingsSnapshot
from utility.performance_metrics import PerformanceCallbackHandler


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_stream_waits_for_model_and_cleans_up(monkeypatch, async_client, outcome):
    closed = asyncio.Event()
    stream_id = "stream-delayed-regression"

    async def events(*args, **kwargs):
        try:
            # Cross two cancellation polls before producing the first token.
            await asyncio.sleep(1.1)
            if outcome == "error":
                raise ConnectionError("Model endpoint unavailable")
            yield {
                "event": "on_chat_model_stream",
                "data": {"chunk": AIMessageChunk(content="Hello")},
            }
            yield {
                "event": "on_chain_end",
                "name": "GeoAgent",
                "data": {"output": {"messages": [AIMessage(content="Hello")]}},
            }
        finally:
            closed.set()

    options = SettingsSnapshot(
        geoserver_backends=[],
        model_settings={"model_provider": "vllm", "model_name": "test", "max_tokens": 256},
        tools=[],
    )
    options.model_settings.enable_agent_audit = False
    monkeypatch.setattr(
        nalamap,
        "_prepare_chat_context",
        AsyncMock(
            return_value=(
                {"messages": []},
                SimpleNamespace(astream_events=events),
                options,
                PerformanceCallbackHandler(),
                "test-delayed-session",
                stream_id,
            )
        ),
    )
    monkeypatch.setattr(nalamap, "_persist_conversation_turn", AsyncMock())

    async def cancel_later():
        await asyncio.sleep(0.65)
        nalamap._cancellation_flags[stream_id] = True

    cancel_task = asyncio.create_task(cancel_later()) if outcome == "cancel" else None
    try:
        response = await async_client.post("/api/chat/stream", json={"query": "Hello"})
    finally:
        if cancel_task:
            await cancel_task
    assert response.status_code == 200
    assert closed.is_set()
    assert stream_id not in nalamap._cancellation_flags
    if outcome == "success":
        assert "event: llm_token" in response.text
        assert "event: result" in response.text
        assert "Hello" in response.text
    elif outcome == "error":
        assert "event: error" in response.text
        assert "Model endpoint unavailable" in response.text
        assert '"status": "complete"' not in response.text
    else:
        assert "event: cancelled" in response.text
        assert "event: result" not in response.text
