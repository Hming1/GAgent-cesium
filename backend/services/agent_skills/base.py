"""Shared definitions for agent Skill modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence

from langchain_core.tools import BaseTool


@dataclass(frozen=True)
class ToolDisplayMetadata:
    """Configuration metadata used by the settings API and UI."""

    display_name: str
    category: str
    group: Optional[str] = None
    enabled: bool = True

    def as_settings_metadata(self) -> Dict[str, object]:
        return {
            "display_name": self.display_name,
            "category": self.category,
            "group": self.group,
            "enabled": self.enabled,
        }


@dataclass(frozen=True)
class SelectorToolMetadata:
    """Semantic metadata used by the dynamic tool selector."""

    name: str
    category: str
    description: str
    always_include: bool = False
    usage_weight: float = 1.0


@dataclass(frozen=True)
class KeywordTrigger:
    """A deterministic routing rule for explicit user wording."""

    terms: Sequence[str]
    tool_keys: Sequence[str]
    require_any_terms: Sequence[str] = field(default_factory=tuple)

    def matches(self, query: str) -> bool:
        query_lower = query.lower()
        has_primary_term = any(term.lower() in query_lower for term in self.terms)
        if not has_primary_term:
            return False
        if not self.require_any_terms:
            return True
        return any(term.lower() in query_lower for term in self.require_any_terms)


@dataclass(frozen=True)
class AgentSkill:
    """A self-contained capability exposed to the GeoAgent agent."""

    id: str
    display_name: str
    description: str
    tools: Mapping[str, BaseTool] = field(default_factory=dict)
    tool_metadata: Mapping[str, ToolDisplayMetadata] = field(default_factory=dict)
    selector_metadata: Mapping[str, SelectorToolMetadata] = field(default_factory=dict)
    prompt: str = ""
    plan_aliases: Mapping[str, str] = field(default_factory=dict)
    layer_keywords: Sequence[str] = field(default_factory=tuple)
    keyword_triggers: Sequence[KeywordTrigger] = field(default_factory=tuple)
    default_enabled: bool = True
