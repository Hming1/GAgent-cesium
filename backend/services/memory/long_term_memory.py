"""Database-backed long-term memory helpers."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.user_memory import MemoryEvent, UserMemory


async def create_memory(
    db: AsyncSession,
    *,
    user_id: Optional[UUID],
    content: str,
    memory_type: str = "fact",
    summary: Optional[str] = None,
    importance: int = 5,
    source_session_id: Optional[str] = None,
    source_message_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    embedding: Optional[list[float]] = None,
) -> UserMemory:
    """Create a long-term memory record."""
    memory = UserMemory(
        user_id=user_id,
        memory_type=memory_type,
        content=content,
        summary=summary,
        importance=max(1, min(10, importance)),
        source_session_id=source_session_id,
        source_message_id=source_message_id,
        tags=tags or [],
        embedding=embedding,
    )
    db.add(memory)
    await db.flush()
    db.add(
        MemoryEvent(
            user_id=user_id,
            memory_id=memory.id,
            event_type="created",
            payload={"memory_type": memory_type, "source_session_id": source_session_id},
        )
    )
    await db.commit()
    await db.refresh(memory)
    return memory


async def list_memories(
    db: AsyncSession,
    *,
    user_id: Optional[UUID],
    limit: int = 20,
    include_inactive: bool = False,
) -> list[UserMemory]:
    """List recent/high-importance memories for a user."""
    stmt = select(UserMemory).where(UserMemory.user_id == user_id)
    if not include_inactive:
        stmt = stmt.where(UserMemory.is_active.is_(True))
    stmt = stmt.order_by(desc(UserMemory.importance), desc(UserMemory.updated_at)).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def retrieve_relevant_memories(
    db: AsyncSession,
    *,
    user_id: Optional[UUID],
    query: str,
    limit: int = 6,
) -> list[UserMemory]:
    """Retrieve relevant memories.

    This first version intentionally uses simple text matching and importance ordering.
    The schema keeps an embedding field so pgvector-backed retrieval can replace this
    implementation without changing the API surface.
    """
    like = f"%{query[:200]}%" if query else "%"
    stmt = (
        select(UserMemory)
        .where(UserMemory.user_id == user_id)
        .where(UserMemory.is_active.is_(True))
        .where((UserMemory.content.ilike(like)) | (UserMemory.summary.ilike(like)))
        .order_by(desc(UserMemory.importance), desc(UserMemory.updated_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    memories = list(result.scalars().all())
    if memories:
        memory_ids = [memory.id for memory in memories]
        await db.execute(
            update(UserMemory)
            .where(UserMemory.id.in_(memory_ids))
            .values(
                access_count=UserMemory.access_count + 1,
                last_accessed_at=func.now(),
            )
        )
        await db.commit()
    return memories


async def deactivate_memory(
    db: AsyncSession,
    *,
    user_id: Optional[UUID],
    memory_id: UUID,
) -> bool:
    """Soft-delete a memory."""
    stmt = select(UserMemory).where(UserMemory.id == memory_id, UserMemory.user_id == user_id)
    result = await db.execute(stmt)
    memory = result.scalars().first()
    if not memory:
        return False
    memory.is_active = False
    db.add(MemoryEvent(user_id=user_id, memory_id=memory_id, event_type="deleted", payload={}))
    await db.commit()
    return True


def memories_to_context(memories: list[UserMemory]) -> str:
    """Render memories as compact Markdown for prompt injection."""
    lines: list[str] = []
    for memory in memories:
        text_value = memory.summary or memory.content
        tags = memory.tags or []
        tag_text = f" tags={','.join(tags)}" if tags else ""
        lines.append(
            f"- [{memory.memory_type}; importance={memory.importance}{tag_text}] {text_value}"
        )
    return "\n".join(lines)


def memory_to_dict(memory: UserMemory) -> dict[str, Any]:
    """Serialize a memory ORM object."""
    return {
        "id": str(memory.id),
        "user_id": str(memory.user_id) if memory.user_id else None,
        "memory_type": memory.memory_type,
        "content": memory.content,
        "summary": memory.summary,
        "importance": memory.importance,
        "source_session_id": memory.source_session_id,
        "source_message_id": memory.source_message_id,
        "tags": memory.tags or [],
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
        "last_accessed_at": (
            memory.last_accessed_at.isoformat() if memory.last_accessed_at else None
        ),
        "access_count": memory.access_count,
        "is_active": memory.is_active,
    }
