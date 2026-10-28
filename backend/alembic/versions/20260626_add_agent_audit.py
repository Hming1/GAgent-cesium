"""Add agent run audit tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260626_add_agent_audit"
down_revision = "20250602_add_user_memory"
branch_labels = None
depends_on = None


def _has_table(conn, table_name: str) -> bool:
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


def _has_column(conn, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(conn)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def upgrade():
    conn = op.get_bind()

    if not _has_table(conn, "agent_runs"):
        op.create_table(
            "agent_runs",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("session_id", sa.TEXT(), nullable=True),
            sa.Column("conversation_id", sa.TEXT(), nullable=True),
            sa.Column("stream_id", sa.TEXT(), nullable=True),
            sa.Column("endpoint", sa.TEXT(), nullable=False),
            sa.Column("query", sa.TEXT(), nullable=True),
            sa.Column("status", sa.TEXT(), nullable=False, server_default=sa.text("'running'")),
            sa.Column("audit_level", sa.TEXT(), nullable=False, server_default=sa.text("'tool'")),
            sa.Column("model_provider", sa.TEXT(), nullable=True),
            sa.Column("model_name", sa.TEXT(), nullable=True),
            sa.Column("input_messages", postgresql.JSONB(), nullable=True),
            sa.Column("output_messages", postgresql.JSONB(), nullable=True),
            sa.Column("initial_state", postgresql.JSONB(), nullable=True),
            sa.Column("final_state", postgresql.JSONB(), nullable=True),
            sa.Column("options_snapshot", postgresql.JSONB(), nullable=True),
            sa.Column("metrics", postgresql.JSONB(), nullable=True),
            sa.Column("error", postgresql.JSONB(), nullable=True),
            sa.Column(
                "started_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("ended_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
        op.create_index("ix_agent_runs_session_id", "agent_runs", ["session_id"])
        op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
        op.create_index("ix_agent_runs_stream_id", "agent_runs", ["stream_id"])
        op.create_index(
            "ix_agent_runs_session_created",
            "agent_runs",
            ["session_id", "created_at"],
        )
        op.create_index(
            "ix_agent_runs_status_created",
            "agent_runs",
            ["status", "created_at"],
        )

    if not _has_table(conn, "agent_run_events"):
        op.create_table(
            "agent_run_events",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("sequence", sa.INTEGER(), nullable=False),
            sa.Column("event_type", sa.TEXT(), nullable=False),
            sa.Column("name", sa.TEXT(), nullable=True),
            sa.Column("input", postgresql.JSONB(), nullable=True),
            sa.Column("output", postgresql.JSONB(), nullable=True),
            sa.Column("payload", postgresql.JSONB(), nullable=True),
            sa.Column("input_json", postgresql.JSONB(), nullable=True),
            sa.Column("output_json", postgresql.JSONB(), nullable=True),
            sa.Column("payload_json", postgresql.JSONB(), nullable=True),
            sa.Column(
                "created_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index("ix_agent_run_events_run_id", "agent_run_events", ["run_id"])
        op.create_index(
            "ix_agent_run_events_event_type",
            "agent_run_events",
            ["event_type"],
        )
        op.create_index(
            "ix_agent_run_events_run_sequence",
            "agent_run_events",
            ["run_id", "sequence"],
        )
        op.create_index(
            "ix_agent_run_events_run_type",
            "agent_run_events",
            ["run_id", "event_type"],
        )
    else:
        for column_name in ("input_json", "output_json", "payload_json"):
            if not _has_column(conn, "agent_run_events", column_name):
                op.add_column(
                    "agent_run_events",
                    sa.Column(column_name, postgresql.JSONB(), nullable=True),
                )


def downgrade():
    conn = op.get_bind()

    if _has_table(conn, "agent_run_events"):
        op.drop_index("ix_agent_run_events_run_type", table_name="agent_run_events")
        op.drop_index("ix_agent_run_events_run_sequence", table_name="agent_run_events")
        op.drop_index("ix_agent_run_events_event_type", table_name="agent_run_events")
        op.drop_index("ix_agent_run_events_run_id", table_name="agent_run_events")
        op.drop_table("agent_run_events")

    if _has_table(conn, "agent_runs"):
        op.drop_index("ix_agent_runs_status_created", table_name="agent_runs")
        op.drop_index("ix_agent_runs_session_created", table_name="agent_runs")
        op.drop_index("ix_agent_runs_stream_id", table_name="agent_runs")
        op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
        op.drop_index("ix_agent_runs_session_id", table_name="agent_runs")
        op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
        op.drop_table("agent_runs")
