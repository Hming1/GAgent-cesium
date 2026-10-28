"""Identical tool-call hard stop (anti recursion-limit loops)."""

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from services.tools.tool_repeat_guard import (
    fingerprint_tool_args,
    refuse_identical_tool_call,
    reset_identical_call_counts,
)


def _state(session_id: str = "sess-repeat"):
    class Options:
        def __init__(self, sid):
            self.session_id = sid

    return {"options": Options(session_id), "messages": []}


def setup_function():
    reset_identical_call_counts()


def teardown_function():
    reset_identical_call_counts()


def test_fingerprint_ignores_injected_keys():
    a = fingerprint_tool_args({"query": "深圳大学", "state": {"x": 1}, "tool_call_id": "c1"})
    b = fingerprint_tool_args({"query": "深圳大学", "tool_call_id": "c2"})
    assert a == b


def test_allows_up_to_max_then_refuses():
    state = _state()
    args = {"query": "深圳大学", "require_boundary": False}

    first = refuse_identical_tool_call(
        state, "geocode_using_nominatim_to_geostate", "c1", args, max_calls=2
    )
    second = refuse_identical_tool_call(
        state, "geocode_using_nominatim_to_geostate", "c2", args, max_calls=2
    )
    third = refuse_identical_tool_call(
        state, "geocode_using_nominatim_to_geostate", "c3", args, max_calls=2
    )

    assert first is None
    assert second is None
    assert isinstance(third, Command)
    msg = third.update["messages"][-1]
    assert isinstance(msg, ToolMessage)
    assert msg.status == "error"
    assert "identical" in msg.content.lower()
    assert "Do NOT call" in msg.content


def test_different_args_are_independent():
    state = _state()
    assert (
        refuse_identical_tool_call(
            state,
            "geocode_using_overpass_to_geostate",
            "c1",
            {"amenity_key": "park", "location_name": "深圳大学"},
            max_calls=1,
        )
        is None
    )
    assert (
        refuse_identical_tool_call(
            state,
            "geocode_using_overpass_to_geostate",
            "c2",
            {"amenity_key": "hospital", "location_name": "深圳大学"},
            max_calls=1,
        )
        is None
    )
    blocked = refuse_identical_tool_call(
        state,
        "geocode_using_overpass_to_geostate",
        "c3",
        {"amenity_key": "park", "location_name": "深圳大学"},
        max_calls=1,
    )
    assert isinstance(blocked, Command)


def test_sessions_are_isolated():
    args = {"query": "park"}
    assert (
        refuse_identical_tool_call(
            _state("a"), "geocode_using_nominatim_to_geostate", "c1", args, max_calls=1
        )
        is None
    )
    assert (
        refuse_identical_tool_call(
            _state("b"), "geocode_using_nominatim_to_geostate", "c2", args, max_calls=1
        )
        is None
    )
    blocked = refuse_identical_tool_call(
        _state("a"), "geocode_using_nominatim_to_geostate", "c3", args, max_calls=1
    )
    assert isinstance(blocked, Command)
