"""ORM models for user memory records."""

from sqlalchemy import Column, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import BOOLEAN, INTEGER, JSONB, TEXT, TIMESTAMP, UUID

from db.base import Base


class UserMemory(Base):
    """Long-term user memory item."""

    __tablename__ = "user_memory"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    memory_type = Column(TEXT, nullable=False, server_default=text("'fact'"))
    content = Column(TEXT, nullable=False)
    summary = Column(TEXT, nullable=True)
    embedding = Column(JSONB, nullable=True)
    importance = Column(INTEGER, nullable=False, server_default=text("5"))
    source_session_id = Column(TEXT, nullable=True, index=True)
    source_message_id = Column(TEXT, nullable=True)
    tags = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    last_accessed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    access_count = Column(INTEGER, nullable=False, server_default=text("0"))
    is_active = Column(BOOLEAN, nullable=False, server_default=text("true"))

    __table_args__ = (
        Index("ix_user_memory_user_active_importance", "user_id", "is_active", "importance"),
    )


class MemoryEvent(Base):
    """Audit trail for memory lifecycle events."""

    __tablename__ = "memory_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    memory_id = Column(
        UUID(as_uuid=True),
        ForeignKey("user_memory.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event_type = Column(TEXT, nullable=False)
    payload = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
