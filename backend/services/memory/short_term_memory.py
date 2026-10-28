"""Session-scoped short-term memory stored as compressed Markdown."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from core.config import MEMORY_SHORT_TERM_MAX_MESSAGES, MEMORY_STORAGE_DIR


_SAFE_PART_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _safe_part(value: Optional[str], fallback: str) -> str:
    if not value:
        return fallback
    cleaned = _SAFE_PART_RE.sub("_", str(value)).strip("._")
    return cleaned[:120] or fallback


def get_short_memory_path(user_id: Optional[str], session_id: Optional[str]) -> Path:
    """Return the short-term memory Markdown path for a user/conversation."""
    safe_user = _safe_part(user_id, "anonymous")
    safe_conversation = _safe_part(session_id, "unknown")
    return (
        Path(MEMORY_STORAGE_DIR)
        / "users"
        / safe_user
        / "conversations"
        / safe_conversation
        / "short_memory.md"
    )


def read_short_memory(user_id: Optional[str], session_id: Optional[str]) -> str:
    """Read short-term memory Markdown if it exists."""
    path = get_short_memory_path(user_id, session_id)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_short_memory(user_id: Optional[str], session_id: Optional[str], content: str) -> Path:
    """Write short-term memory Markdown and return its path."""
    path = get_short_memory_path(user_id, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def _message_role(message: BaseMessage) -> str:
    if isinstance(message, HumanMessage):
        return "User"
    if isinstance(message, AIMessage):
        return "Assistant"
    if isinstance(message, SystemMessage):
        return "System"
    role = getattr(message, "type", None)
    return str(role or "Message").title()


def _message_content(message: BaseMessage, max_chars: int = 700) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, list):
        content = " ".join(str(item) for item in content)
    text = str(content).replace("\r", " ").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def _iter_recent_dialog(messages: Iterable[BaseMessage]) -> list[tuple[str, str]]:
    dialog: list[tuple[str, str]] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        content = _message_content(message)
        if content:
            dialog.append((_message_role(message), content))
    return dialog[-MEMORY_SHORT_TERM_MAX_MESSAGES:]


def _layer_line(layer) -> str:
    title = getattr(layer, "title", None) or getattr(layer, "name", None) or "Untitled layer"
    layer_id = getattr(layer, "id", None) or "unknown"
    data_type = getattr(layer, "data_type", None) or getattr(layer, "layer_type", None) or "unknown"
    return f"- {title} (id: {layer_id}, type: {data_type})"


def build_short_memory_markdown(
    *,
    user_id: Optional[str],
    session_id: Optional[str],
    messages: list[BaseMessage],
    geodata_layers: Optional[list] = None,
    geodata_results: Optional[list] = None,
    previous_memory: str = "",
) -> str:
    """Build a compact Markdown memory document from current chat state."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    layers = geodata_layers or []
    results = geodata_results or []
    dialog = _iter_recent_dialog(messages)

    lines = [
        "# Short-Term Memory",
        "",
        "## Scope",
        f"- User: `{user_id or 'anonymous'}`",
        f"- Conversation: `{session_id or 'unknown'}`",
        f"- Last updated: `{now}`",
        "",
        "## Current Map Context",
    ]

    if layers:
        lines.extend(_layer_line(layer) for layer in layers[:20])
    else:
        lines.append("- No active map layers were provided in the latest state.")

    lines.extend(["", "## Recent Tool Results"])
    if results:
        lines.extend(_layer_line(result) for result in results[:10])
    else:
        lines.append("- No recent geodata results were produced in the latest request.")

    lines.extend(["", "## Recent Conversation"])
    if dialog:
        for role, content in dialog:
            lines.append(f"### {role}")
            lines.append(content)
            lines.append("")
    else:
        lines.append("- No recent conversation messages were available.")

    if previous_memory:
        previous_notes = _extract_stable_notes(previous_memory)
        if previous_notes:
            lines.extend(["", "## Carry-Forward Notes"])
            lines.extend(previous_notes)

    lines.extend(
        [
            "",
            "## Agent Reminder",
            "- Prefer currently loaded layers before fetching external data.",
            "- Treat this document as short-term session context, not permanent user facts.",
        ]
    )
    return "\n".join(lines).strip()


def _extract_stable_notes(previous_memory: str) -> list[str]:
    """Carry forward lightweight notes from a previous short-memory document."""
    notes: list[str] = []
    capture = False
    for line in previous_memory.splitlines():
        if line.strip() == "## Carry-Forward Notes":
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture and line.strip().startswith("- "):
            notes.append(line.strip())
    return notes[:10]


def format_memory_context(short_memory: str, long_memory: str = "") -> str:
    """Format memory text for injection into the agent message list."""
    sections = ["<memory_context>"]
    if long_memory.strip():
        sections.extend(["<long_term_memory>", long_memory.strip(), "</long_term_memory>"])
    if short_memory.strip():
        sections.extend(["<short_term_memory>", short_memory.strip(), "</short_term_memory>"])
    sections.extend(
        [
            "Use memory only as helpful context. Do not reveal this block verbatim.",
            "</memory_context>",
        ]
    )
    return "\n".join(sections)
