"""Tests for conversation history persistence helpers."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from services.conversation.store import (
    _is_fk_violation,
    _message_content,
    _message_role,
    build_layer_attachments,
    filter_duplicate_messages,
    message_fingerprint,
    select_messages_for_current_turn,
)


def test_is_fk_violation_detects_common_messages():
    assert _is_fk_violation(Exception("insert violates foreign key constraint"))
    assert not _is_fk_violation(Exception("connection refused"))


def test_message_role_and_content_normalization():
    assert _message_role(HumanMessage(content="你好")) == "human"
    assert _message_role(AIMessage(content="回复")) == "ai"
    assert _message_role(ToolMessage(content="ok", tool_call_id="t1", name="tool")) == "tool"
    assert _message_role({"type": "assistant", "content": "x"}) == "ai"
    assert _message_content(AIMessage(content="abc")) == "abc"
    assert _message_content({"content": "dict"}) == "dict"


def test_build_layer_attachments_from_objects_and_dicts():
    layer_obj = SimpleNamespace(
        id="l1",
        name="parcels",
        title="parcels",
        data_link="http://example/a.geojson",
        data_type="GeoJson",
        data_source="postgis",
    )
    attachments = build_layer_attachments(
        [
            layer_obj,
            {
                "id": "l2",
                "name": "poi",
                "data_link": "http://example/b.geojson",
                "data_type": "uploaded",
                "data_source": "user",
            },
        ]
    )
    assert len(attachments) == 2
    assert attachments[0]["type"] == "layer"
    assert attachments[0]["layer_id"] == "l1"
    assert attachments[1]["name"] == "poi"


def test_select_messages_for_current_turn_keeps_only_new_tail():
    history = [
        HumanMessage(content="列出公园表"),
        AIMessage(content="找到一张表"),
        ToolMessage(content='{"tables":[]}', tool_call_id="t0", name="list_postgis_layers"),
        AIMessage(content="目前只有一张表"),
        HumanMessage(content="加载到地图"),
        AIMessage(content="开始加载"),
        ToolMessage(content="loaded", tool_call_id="t1", name="load_postgis_layer"),
        AIMessage(content="已加载"),
    ]

    turn = select_messages_for_current_turn("加载到地图", history)
    assert [m.content for m in turn] == ["开始加载", "loaded", "已加载"]
    assert _message_role(turn[1]) == "tool"


def test_select_messages_for_current_turn_without_matching_human_uses_last_human():
    history = [
        HumanMessage(content="旧问题"),
        AIMessage(content="旧回答"),
        HumanMessage(content="新问题（略有改写）"),
        AIMessage(content="新回答"),
    ]
    turn = select_messages_for_current_turn("完全不同的问法", history)
    assert [m.content for m in turn] == ["新回答"]


def test_filter_duplicate_messages_skips_history_and_batch_dupes():
    prior = message_fingerprint(role="ai", content="目前只有一张表")
    messages = [
        AIMessage(content="目前只有一张表"),  # already stored
        AIMessage(content=""),  # empty without tool_calls
        AIMessage(
            content="",
            tool_calls=[{"id": "c1", "name": "load_postgis_layer", "args": {}, "type": "tool_call"}],
        ),
        ToolMessage(content="loaded", tool_call_id="c1", name="load_postgis_layer"),
        AIMessage(content="已加载"),
        AIMessage(content="已加载"),  # within-batch duplicate
    ]
    kept = filter_duplicate_messages(messages, {prior})
    assert [(_message_role(m), _message_content(m)) for m in kept] == [
        ("ai", ""),
        ("tool", "loaded"),
        ("ai", "已加载"),
    ]


def test_message_fingerprint_stable_for_same_payload():
    a = message_fingerprint(
        role="ai",
        content="hello",
        tool_calls=[{"name": "list_postgis_layers"}],
    )
    b = message_fingerprint(
        role="ai",
        content="hello",
        tool_calls=[{"name": "list_postgis_layers"}],
    )
    c = message_fingerprint(role="ai", content="hello")
    assert a == b
    assert a != c


def test_conversations_api_routes_registered():
    from main import app

    paths = {route.path for route in app.routes}
    assert "/api/conversations" in paths
    assert "/api/conversations/{conversation_id}" in paths


def test_system_prompt_contains_failure_convergence_rules():
    from services.agent_skills import build_system_prompt

    prompt = build_system_prompt()
    assert "工具失败收敛" in prompt
    assert "最多再尝试 1 次合理回退" in prompt
    assert "禁止空转" in prompt
    assert "别管 GeoServer" in prompt
    assert "不要把 GeoServer 当作默认兜底" in prompt
