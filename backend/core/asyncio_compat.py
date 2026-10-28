"""Cross-platform asyncio compatibility helpers."""

import asyncio
import sys


def configure_windows_selector_event_loop() -> bool:
    """Use the event loop required by psycopg async connections on Windows."""
    if not sys.platform.startswith("win"):
        return False

    policy_class = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_class is None:
        return False

    asyncio.set_event_loop_policy(policy_class())
    return True
