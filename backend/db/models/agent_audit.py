"""ORM models for persisted agent run audit traces."""

from sqlalchemy import Column, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import INTEGER, JSONB, TEXT, TIMESTAMP, UUID

from db.base import Base


class AgentRun(Base):
    """One top-level agent request/response execution."""

    __tablename__ = "agent_runs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_id = Column(TEXT, nullable=True, index=True)
    conversation_id = Column(TEXT, nullable=True, index=True)
    stream_id = Column(TEXT, nullable=True, index=True)
    endpoint = Column(TEXT, nullable=False)
    query = Column(TEXT, nullable=True)
    status = Column(TEXT, nullable=False, server_default=text("'running'"))
    audit_level = Column(TEXT, nullable=False, server_default=text("'tool'"))
    model_provider = Column(TEXT, nullable=True)
    model_name = Column(TEXT, nullable=True)
    input_messages = Column(JSONB, nullable=True)
    output_messages = Column(JSONB, nullable=True)
    initial_state = Column(JSONB, nullable=True)
    final_state = Column(JSONB, nullable=True)
    options_snapshot = Column(JSONB, nullable=True)
    metrics = Column(JSONB, nullable=True)
    error = Column(JSONB, nullable=True)
    started_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    ended_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ix_agent_runs_session_created", "session_id", "created_at"),
        Index("ix_agent_runs_status_created", "status", "created_at"),
    )


class AgentRunEvent(Base):
    """Ordered audit events for an agent run."""

    __tablename__ = "agent_run_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence = Column(INTEGER, nullable=False)
    event_type = Column(TEXT, nullable=False, index=True)
    name = Column(TEXT, nullable=True)
    input = Column(JSONB, nullable=True)
    output = Column(JSONB, nullable=True)
    payload = Column(JSONB, nullable=True)
    input_json = Column(JSONB, nullable=True)
    output_json = Column(JSONB, nullable=True)
    payload_json = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ix_agent_run_events_run_sequence", "run_id", "sequence"),
        Index("ix_agent_run_events_run_type", "run_id", "event_type"),
    )
