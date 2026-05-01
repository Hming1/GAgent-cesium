"""Interpreter startup customizations for local development/runtime.

This module is auto-imported by Python's site initialization when present
on sys.path. We use it to enforce an asyncio policy compatible with psycopg
async connections on Windows.
"""

import asyncio
import sys


if sys.platform.startswith("win"):
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is not None:
        asyncio.set_event_loop_policy(policy_cls())
