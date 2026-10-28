"""Add conversation and conversation_messages tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261012_add_conversations"
down_revision = "20260724_registration_invites"
branch_labels = None
depends_on = None


def _has_table(conn, table_name: str) -> bool:
    return sa.inspect(conn).has_table(table_name)


def upgrade():
    conn = op.get_bind()

    if not _has_table(conn, "conversations"):
        op.create_table(
            "conversations",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("conversation_id", sa.TEXT(), nullable=False),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("session_id", sa.TEXT(), nullable=True),
            sa.Column("title", sa.TEXT(), nullable=True),
            sa.Column("status", sa.TEXT(), nullable=False, server_default=sa.text("'active'")),
            sa.Column("message_count", sa.INTEGER(), nullable=False, server_default=sa.text("0")),
            sa.Column("last_message_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("metadata", postgresql.JSONB(), nullable=True),
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
            sa.UniqueConstraint("conversation_id", name="uq_conversations_conversation_id"),
        )
        op.create_index("ix_conversations_conversation_id", "conversations", ["conversation_id"])
        op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
        op.create_index("ix_conversations_session_id", "conversations", ["session_id"])
        op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"])
        op.create_index(
            "ix_conversations_session_updated", "conversations", ["session_id", "updated_at"]
        )

    if not _has_table(conn, "conversation_messages"):
        op.create_table(
            "conversation_messages",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "conversation_pk",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("conversation_id", sa.TEXT(), nullable=False),
            sa.Column("sequence", sa.INTEGER(), nullable=False),
            sa.Column("role", sa.TEXT(), nullable=False),
            sa.Column("content", sa.TEXT(), nullable=True),
            sa.Column("message_type", sa.TEXT(), nullable=True),
            sa.Column("client_message_id", sa.TEXT(), nullable=True),
            sa.Column(
                "run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("agent_runs.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("name", sa.TEXT(), nullable=True),
            sa.Column("tool_call_id", sa.TEXT(), nullable=True),
            sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
            sa.Column("attachments", postgresql.JSONB(), nullable=True),
            sa.Column("extra", postgresql.JSONB(), nullable=True),
            sa.Column(
                "created_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "conversation_pk",
                "sequence",
                name="uq_conversation_messages_pk_sequence",
            ),
        )
        op.create_index(
            "ix_conversation_messages_conversation_pk",
            "conversation_messages",
            ["conversation_pk"],
        )
        op.create_index(
            "ix_conversation_messages_conversation_id",
            "conversation_messages",
            ["conversation_id"],
        )
        op.create_index("ix_conversation_messages_run_id", "conversation_messages", ["run_id"])
        op.create_index(
            "ix_conversation_messages_conv_sequence",
            "conversation_messages",
            ["conversation_id", "sequence"],
        )
        op.create_index(
            "ix_conversation_messages_created",
            "conversation_messages",
            ["created_at"],
        )


def downgrade():
    conn = op.get_bind()
    if _has_table(conn, "conversation_messages"):
        op.drop_table("conversation_messages")
    if _has_table(conn, "conversations"):
        op.drop_table("conversations")
