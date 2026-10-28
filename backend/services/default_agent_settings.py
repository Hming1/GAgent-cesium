"""Default agent tools, metadata and system prompt.

These values are derived from the Skill modules in ``services/agent_skills``,
which are the single source of truth. This module only keeps the names that
existing callers (settings API, single agent, deployment config loader) import.
"""

from typing import Dict, List

from langchain_core.tools import BaseTool

from services.agent_skills import (
    build_available_tools,
    build_system_prompt,
    build_tool_metadata,
)

# Tool metadata for configuration and UI display
TOOL_METADATA: Dict[str, Dict[str, object]] = build_tool_metadata()

DEFAULT_SYSTEM_PROMPT: str = build_system_prompt()

DEFAULT_AVAILABLE_TOOLS: Dict[str, BaseTool] = build_available_tools()

DEFAULT_SELECTED_TOOLS: List[str] = []
