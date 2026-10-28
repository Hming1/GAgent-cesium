"""Tests for platform-specific asyncio setup."""

from core import asyncio_compat


def test_configures_selector_event_loop_on_windows(monkeypatch):
    configured_policies = []

    class FakeSelectorPolicy:
        pass

    monkeypatch.setattr(asyncio_compat.sys, "platform", "win32")
    monkeypatch.setattr(
        asyncio_compat.asyncio,
        "WindowsSelectorEventLoopPolicy",
        FakeSelectorPolicy,
        raising=False,
    )
    monkeypatch.setattr(
        asyncio_compat.asyncio,
        "set_event_loop_policy",
        configured_policies.append,
    )

    assert asyncio_compat.configure_windows_selector_event_loop() is True
    assert len(configured_policies) == 1
    assert isinstance(configured_policies[0], FakeSelectorPolicy)


def test_does_not_change_event_loop_on_other_platforms(monkeypatch):
    configured_policies = []
    monkeypatch.setattr(asyncio_compat.sys, "platform", "linux")
    monkeypatch.setattr(
        asyncio_compat.asyncio,
        "set_event_loop_policy",
        configured_policies.append,
    )

    assert asyncio_compat.configure_windows_selector_event_loop() is False
    assert configured_policies == []
