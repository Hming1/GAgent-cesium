"""Persist and query chat conversation history."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set
from uuid import UUID

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.conversation import Conversation, ConversationMessage
from services.agent_audit.serializers import sanitize_for_audit, to_jsonable

logger = logging.getLogger(__name__)


def _is_fk_violation(exc: BaseException) -> bool:
    """Detect Postgres / SQLAlchemy foreign-key integrity errors."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return (
        "foreign key" in text
        or "foreignkeyviolation" in text
        or "fk_" in text
        or getattr(exc, "orig", None) is not None
        and "foreign key" in str(getattr(exc, "orig", "")).lower()
    )


def message_fingerprint(
    *,
    role: str,
    content: Optional[str],
    tool_call_id: Optional[str] = None,
    tool_calls: Any = None,
    name: Optional[str] = None,
) -> str:
    """Stable fingerprint used to skip already-persisted agent history."""
    # Empty assistant messages can invoke the same tool many times. Include
    # call IDs and arguments so every result retains its matching invocation.
    calls_json = (
        json.dumps(to_jsonable(tool_calls), sort_keys=True) if tool_calls else ""
    )
    payload = "|".join(
        [
            str(role or ""),
            (content or "").strip(),
            str(tool_call_id or ""),
            str(name or ""),
            calls_json,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_messages_for_current_turn(
    query: Optional[str],
    result_messages: Optional[Sequence[Any]],
) -> List[Any]:
    """Keep only messages after the current user query in the agent history.

    LangGraph / agent state usually returns the full message list. Persisting
    that whole list every turn rewrites prior AI/tool replies into
    ``conversation_messages``.
    """
    messages = list(result_messages or [])
    if not messages:
        return []

    query_norm = (query or "").strip()
    cut_index = -1
    for index, msg in enumerate(messages):
        if _message_role(msg) != "human":
            continue
        content = (_message_content(msg) or "").strip()
        if query_norm and content == query_norm:
            cut_index = index
        elif not query_norm:
            cut_index = index

    if cut_index < 0:
        for index in range(len(messages) - 1, -1, -1):
            if _message_role(messages[index]) == "human":
                cut_index = index
                break

    if cut_index < 0:
        return messages
    return messages[cut_index + 1 :]


def filter_duplicate_messages(
    messages: Sequence[Any],
    existing_fingerprints: Optional[Iterable[str]] = None,
) -> List[Any]:
    """Drop messages already stored (or duplicated within this turn batch)."""
    seen: Set[str] = set(existing_fingerprints or [])
    kept: List[Any] = []
    for msg in messages:
        role = _message_role(msg)
        if role in {"human", "system"}:
            continue
        content = _message_content(msg)
        tool_calls = _tool_calls(msg)
        if role == "ai" and (content is None or str(content).strip() == ""):
            if not tool_calls:
                continue
        fingerprint = message_fingerprint(
            role=role,
            content=content,
            tool_call_id=_tool_call_id(msg),
            tool_calls=tool_calls,
            name=_message_name(msg),
        )
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        kept.append(msg)
    return kept


def _message_role(msg: Any) -> str:
    msg_type = getattr(msg, "type", None)
    if not msg_type and isinstance(msg, dict):
        msg_type = msg.get("type") or msg.get("role")
    mapping = {
        "human": "human",
        "user": "human",
        "ai": "ai",
        "assistant": "ai",
        "system": "system",
        "tool": "tool",
        "function": "tool",
    }
    return mapping.get(str(msg_type or "").lower(), str(msg_type or "unknown"))


def _message_content(msg: Any) -> Optional[str]:
    content = getattr(msg, "content", None)
    if content is None and isinstance(msg, dict):
        content = msg.get("content")
    if content is None:
        return None
    if isinstance(content, str):
        return content
    try:
        return str(to_jsonable(content))
    except Exception:
        return str(content)


def _message_type(msg: Any) -> Optional[str]:
    msg_type = getattr(msg, "type", None)
    if msg_type:
        return str(msg_type)
    if isinstance(msg, dict):
        return str(msg.get("type") or msg.get("role") or "")
    return None


def _tool_calls(msg: Any) -> Any:
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls is None and isinstance(msg, dict):
        tool_calls = msg.get("tool_calls")
    return sanitize_for_audit(tool_calls) if tool_calls else None


def _tool_call_id(msg: Any) -> Optional[str]:
    value = getattr(msg, "tool_call_id", None)
    if value is None and isinstance(msg, dict):
        value = msg.get("tool_call_id")
    return str(value) if value else None


def _message_name(msg: Any) -> Optional[str]:
    value = getattr(msg, "name", None)
    if value is None and isinstance(msg, dict):
        value = msg.get("name")
    return str(value) if value else None


def build_layer_attachments(layers: Optional[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Build attachment refs from map layers involved in a turn."""
    attachments: List[Dict[str, Any]] = []
    for layer in layers or []:
        if isinstance(layer, dict):
            attachments.append(
                {
                    "type": "layer",
                    "layer_id": layer.get("id"),
                    "name": layer.get("name") or layer.get("title"),
                    "data_link": layer.get("data_link"),
                    "data_type": layer.get("data_type"),
                    "data_source": layer.get("data_source"),
                }
            )
            continue
        attachments.append(
            {
                "type": "layer",
                "layer_id": getattr(layer, "id", None),
                "name": getattr(layer, "name", None) or getattr(layer, "title", None),
                "data_link": getattr(layer, "data_link", None),
                "data_type": getattr(layer, "data_type", None),
                "data_source": getattr(layer, "data_source", None),
            }
        )
    return attachments


def conversation_to_dict(row: Conversation) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "conversation_id": row.conversation_id,
        "user_id": str(row.user_id) if row.user_id else None,
        "session_id": row.session_id,
        "title": row.title,
        "status": row.status,
        "message_count": row.message_count or 0,
        "last_message_at": (
            row.last_message_at.isoformat() if row.last_message_at else None
        ),
        "metadata": row.meta,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def message_to_dict(row: ConversationMessage) -> Dict[str, Any]:
    return {
        "id": str(row.id),
        "conversation_id": row.conversation_id,
        "sequence": row.sequence,
        "role": row.role,
        "content": row.content,
        "message_type": row.message_type,
        "client_message_id": row.client_message_id,
        "run_id": str(row.run_id) if row.run_id else None,
        "name": row.name,
        "tool_call_id": row.tool_call_id,
        "tool_calls": row.tool_calls,
        "attachments": row.attachments,
        "extra": row.extra,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


class ConversationStore:
    """Best-effort conversation persistence (never breaks the chat path)."""

    def __init__(self, db: Optional[AsyncSession]):
        self.db = db

    @property
    def enabled(self) -> bool:
        return self.db is not None

    async def ensure_conversation(
        self,
        *,
        conversation_id: str,
        user_id: Optional[UUID] = None,
        session_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Conversation]:
        if not self.enabled or not conversation_id:
            return None
        try:
            result = await self.db.execute(
                select(Conversation).where(
                    Conversation.conversation_id == conversation_id
                )
            )
            row = result.scalar_one_or_none()
            if row:
                changed = False
                if user_id and row.user_id is None:
                    row.user_id = user_id
                    changed = True
                if session_id and row.session_id != session_id:
                    row.session_id = session_id
                    changed = True
                if title and not row.title:
                    row.title = title
                    changed = True
                if changed:
                    await self.db.commit()
                    await self.db.refresh(row)
                return row

            row = Conversation(
                conversation_id=conversation_id,
                user_id=user_id,
                session_id=session_id,
                title=title,
                status="active",
                message_count=0,
            )
            self.db.add(row)
            await self.db.commit()
            await self.db.refresh(row)
            return row
        except Exception as exc:
            logger.warning("Failed to ensure conversation %s: %s", conversation_id, exc)
            await self._rollback()
            return None

    async def _next_sequence(self, conversation_pk: UUID) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.max(ConversationMessage.sequence), 0)).where(
                ConversationMessage.conversation_pk == conversation_pk
            )
        )
        return int(result.scalar_one() or 0) + 1

    async def append_message(
        self,
        *,
        conversation: Conversation,
        role: str,
        content: Optional[str],
        message_type: Optional[str] = None,
        run_id: Optional[UUID] = None,
        name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tool_calls: Any = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        extra: Optional[Dict[str, Any]] = None,
        client_message_id: Optional[str] = None,
    ) -> Optional[ConversationMessage]:
        if not self.enabled:
            return None
        try:
            sequence = await self._next_sequence(conversation.id)
            # Cap tool payloads so history restore stays browser-safe (OSM
            # list_fields can be hundreds of KB otherwise).
            stored_content = content
            if (
                role == "tool"
                and isinstance(stored_content, str)
                and len(stored_content) > 8000
            ):
                stored_content = (
                    f"{stored_content[:8000]}\n"
                    f"...[truncated {len(stored_content) - 8000} chars for history]"
                )
            msg = ConversationMessage(
                conversation_pk=conversation.id,
                conversation_id=conversation.conversation_id,
                sequence=sequence,
                role=role,
                content=stored_content,
                message_type=message_type or role,
                client_message_id=client_message_id,
                run_id=run_id,
                name=name,
                tool_call_id=tool_call_id,
                tool_calls=sanitize_for_audit(tool_calls) if tool_calls else None,
                attachments=sanitize_for_audit(attachments) if attachments else None,
                extra=sanitize_for_audit(extra) if extra else None,
            )
            self.db.add(msg)
            await self.db.execute(
                update(Conversation)
                .where(Conversation.id == conversation.id)
                .values(
                    message_count=sequence,
                    last_message_at=func.now(),
                    updated_at=func.now(),
                    title=conversation.title
                    or (
                        content[:80]
                        if role == "human" and content
                        else conversation.title
                    ),
                )
            )
            await self.db.commit()
            await self.db.refresh(msg)
            return msg
        except Exception as exc:
            # Common when audit run was rolled back but a stale run_id was passed.
            await self._rollback()
            if run_id is not None and _is_fk_violation(exc):
                logger.warning("Retry append without run_id after FK failure: %s", exc)
                return await self.append_message(
                    conversation=conversation,
                    role=role,
                    content=content,
                    message_type=message_type,
                    run_id=None,
                    name=name,
                    tool_call_id=tool_call_id,
                    tool_calls=tool_calls,
                    attachments=attachments,
                    extra=extra,
                    client_message_id=client_message_id,
                )
            logger.warning("Failed to append conversation message: %s", exc)
            return None

    async def _existing_fingerprints(self, conversation_pk: UUID) -> Set[str]:
        result = await self.db.execute(
            select(
                ConversationMessage.role,
                ConversationMessage.content,
                ConversationMessage.tool_call_id,
                ConversationMessage.tool_calls,
                ConversationMessage.name,
            ).where(ConversationMessage.conversation_pk == conversation_pk)
        )
        fingerprints: Set[str] = set()
        for role, content, tool_call_id, tool_calls, name in result.all():
            fingerprints.add(
                message_fingerprint(
                    role=str(role or ""),
                    content=content,
                    tool_call_id=tool_call_id,
                    tool_calls=tool_calls,
                    name=name,
                )
            )
        return fingerprints

    async def record_turn(
        self,
        *,
        conversation_id: str,
        user_id: Optional[UUID],
        session_id: Optional[str],
        query: Optional[str],
        result_messages: Optional[Sequence[Any]],
        run_id: Optional[UUID] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        include_tool_messages: bool = True,
    ) -> None:
        """Persist one user turn + new assistant/tool outputs only.

        Incremental rules:
        1. Slice agent history to messages after the current human query.
        2. Skip fingerprints already stored for this conversation.
        3. Skip duplicates within the same turn batch.
        """
        if not self.enabled or not conversation_id:
            return

        title = (query or "").strip()[:80] or None
        conversation = await self.ensure_conversation(
            conversation_id=conversation_id,
            user_id=user_id,
            session_id=session_id,
            title=title,
        )
        if conversation is None:
            return

        try:
            existing = await self._existing_fingerprints(conversation.id)
        except Exception as exc:
            logger.warning("Failed to load conversation fingerprints: %s", exc)
            await self._rollback()
            existing = set()

        query_text = (query or "").strip()
        if query_text:
            # Always record the human turn once; agent history humans are skipped below.
            await self.append_message(
                conversation=conversation,
                role="human",
                content=query_text,
                message_type="human",
                run_id=run_id,
                attachments=attachments,
                extra={"source": "chat_turn"},
            )
            existing.add(message_fingerprint(role="human", content=query_text))

        turn_messages = select_messages_for_current_turn(query_text, result_messages)
        if not include_tool_messages:
            turn_messages = [
                msg for msg in turn_messages if _message_role(msg) != "tool"
            ]
        new_messages = filter_duplicate_messages(turn_messages, existing)

        for msg in new_messages:
            role = _message_role(msg)
            content = _message_content(msg)
            await self.append_message(
                conversation=conversation,
                role=role,
                content=content,
                message_type=_message_type(msg),
                run_id=run_id,
                name=_message_name(msg),
                tool_call_id=_tool_call_id(msg),
                tool_calls=_tool_calls(msg),
                extra={"source": "agent_result"},
            )

    async def list_conversations(
        self,
        *,
        user_id: Optional[UUID] = None,
        session_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        stmt = select(Conversation).where(Conversation.status == "active")
        if user_id:
            stmt = stmt.where(Conversation.user_id == user_id)
        elif session_id:
            stmt = stmt.where(Conversation.session_id == session_id)
        else:
            return []
        stmt = stmt.order_by(desc(Conversation.updated_at)).offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        return [conversation_to_dict(row) for row in result.scalars().all()]

    async def get_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
        include_tool_messages: bool = True,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"conversation": None, "messages": []}

        conv_result = await self.db.execute(
            select(Conversation).where(Conversation.conversation_id == conversation_id)
        )
        conversation = conv_result.scalar_one_or_none()
        if conversation is None:
            return {"conversation": None, "messages": []}

        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_pk == conversation.id)
            .order_by(ConversationMessage.sequence.asc())
            .offset(offset)
            .limit(limit)
        )
        if not include_tool_messages:
            stmt = stmt.where(ConversationMessage.role != "tool")
        msg_result = await self.db.execute(stmt)
        messages = [message_to_dict(row) for row in msg_result.scalars().all()]
        return {
            "conversation": conversation_to_dict(conversation),
            "messages": messages,
        }

    async def _rollback(self) -> None:
        if self.db is None:
            return
        try:
            await self.db.rollback()
        except Exception:
            logger.exception("Failed to roll back conversation transaction")
