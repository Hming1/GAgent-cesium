"""ORM models for persisted chat conversations and messages."""

from sqlalchemy import Column, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import INTEGER, JSONB, TEXT, TIMESTAMP, UUID

from db.base import Base


class Conversation(Base):
    """One user-facing chat conversation (may span many agent runs)."""

    __tablename__ = "conversations"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    conversation_id = Column(TEXT, nullable=False, unique=True, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id = Column(TEXT, nullable=True, index=True)
    title = Column(TEXT, nullable=True)
    status = Column(TEXT, nullable=False, server_default=text("'active'"))
    message_count = Column(INTEGER, nullable=False, server_default=text("0"))
    last_message_at = Column(TIMESTAMP(timezone=True), nullable=True)
    meta = Column("metadata", JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
        Index("ix_conversations_session_updated", "session_id", "updated_at"),
    )


class ConversationMessage(Base):
    """Ordered message within a conversation."""

    __tablename__ = "conversation_messages"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    conversation_pk = Column(
        "conversation_pk",
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id = Column(TEXT, nullable=False, index=True)
    sequence = Column(INTEGER, nullable=False)
    role = Column(TEXT, nullable=False)
    content = Column(TEXT, nullable=True)
    message_type = Column(TEXT, nullable=True)
    client_message_id = Column(TEXT, nullable=True)
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(TEXT, nullable=True)
    tool_call_id = Column(TEXT, nullable=True)
    tool_calls = Column(JSONB, nullable=True)
    attachments = Column(JSONB, nullable=True)
    extra = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "conversation_pk",
            "sequence",
            name="uq_conversation_messages_pk_sequence",
        ),
        Index("ix_conversation_messages_conv_sequence", "conversation_id", "sequence"),
        Index("ix_conversation_messages_created", "created_at"),
    )
