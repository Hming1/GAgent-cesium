"""Text-based execution plan extraction fallback.

When a local LLM (e.g. Qwen on vLLM) fails to emit a proper
create_execution_plan tool call, the model may instead write the plan
as plain markdown text. This module detects such text-only plans and
converts them into the same execution_plan dict structure the tool
would have produced, so the plan-mode UI flow works even without a
real tool call.
"""

import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage


_PLAN_INDICATORS = ("\u8ba1\u5212",)
_PLAN_SECONDARY = ("\u6b65\u9aa4", "\u786e\u8ba4", "\u6267\u884c")
_MIN_PLAN_LEN = 80


def _extract_title(content: str) -> str:
    m = re.search(r"^#{1,3}\s+(.+)$", content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\*\*(?:\u76ee\u6807|\u6807\u9898)\*\*[\uff1a:]\s*(.+)", content)
    if m:
        return m.group(1).strip()
    return "\u6267\u884c\u8ba1\u5212"


def _extract_steps(content: str) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    for m in re.finditer(
        r"^\d+[.\u3001)]\s*\*\*(.+?)\*\*\s*[-\u2014\u2013:\uff1a]\s*(.+)$",
        content,
        re.MULTILINE,
    ):
        action_text = f"{m.group(1).strip()} - {m.group(2).strip()}"
        steps.append({"action": action_text, "tool": "", "reason": ""})
    if steps:
        return steps
    for m in re.finditer(r"^\d+[.\u3001)]\s+(.+)$", content, re.MULTILINE):
        line = m.group(1).strip()
        if line.startswith("\u8bf7") or line.startswith("\u9884\u671f"):
            continue
        steps.append({"action": line, "tool": "", "reason": ""})
    return steps


def _extract_summary(content: str) -> str:
    m = re.search(
        r"\*\*(?:\u9884\u671f\u8f93\u51fa|\u9884\u671f\u7ed3\u679c|\u9884\u671f)\*\*[\uff1a:]\s*(.+?)(?=\n\n|\Z)",
        content,
        re.DOTALL,
    )
    if m:
        return m.group(1).strip().replace("\n", " ")[:300]
    paragraphs = [p.strip() for p in content.strip().split("\n\n") if p.strip()]
    for p in reversed(paragraphs):
        if not p.startswith("#") and not re.match(r"^\d+[.\u3001)]", p):
            return p[:300]
    return content.strip()[:200]


def extract_plan_from_text(content: str) -> Optional[Dict[str, Any]]:
    """Try to extract an execution plan from AI message text."""
    if not content or len(content) < _MIN_PLAN_LEN:
        return None
    if not any(ind in content for ind in _PLAN_INDICATORS):
        return None
    if not any(ind in content for ind in _PLAN_SECONDARY):
        return None
    steps = _extract_steps(content)
    if not steps:
        return None
    return {
        "title": _extract_title(content),
        "steps": steps,
        "summary": _extract_summary(content),
        "status": "pending",
        "step_count": len(steps),
    }


def maybe_extract_plan_from_messages(
    messages: List[BaseMessage],
) -> Optional[Dict[str, Any]]:
    """Check the last AI message for a text-only plan."""
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = str(getattr(msg, "content", "") or "")
            if content:
                return extract_plan_from_text(content)
        break
    return None
