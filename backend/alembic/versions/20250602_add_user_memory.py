"""Add user memory tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20250602_add_user_memory"
down_revision = "20250310_add_owner_payload"
branch_labels = None
depends_on = None


def _has_table(conn, table_name: str) -> bool:
    inspector = sa.inspect(conn)
    return inspector.has_table(table_name)


def upgrade():
    conn = op.get_bind()

    if not _has_table(conn, "user_memory"):
        op.create_table(
            "user_memory",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("memory_type", sa.TEXT(), nullable=False, server_default=sa.text("'fact'")),
            sa.Column("content", sa.TEXT(), nullable=False),
            sa.Column("summary", sa.TEXT(), nullable=True),
            sa.Column("embedding", postgresql.JSONB(), nullable=True),
            sa.Column("importance", sa.INTEGER(), nullable=False, server_default=sa.text("5")),
            sa.Column("source_session_id", sa.TEXT(), nullable=True),
            sa.Column("source_message_id", sa.TEXT(), nullable=True),
            sa.Column("tags", postgresql.JSONB(), nullable=True),
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
            sa.Column("last_accessed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("access_count", sa.INTEGER(), nullable=False, server_default=sa.text("0")),
            sa.Column("is_active", sa.BOOLEAN(), nullable=False, server_default=sa.text("true")),
        )
        op.create_index("ix_user_memory_user_id", "user_memory", ["user_id"])
        op.create_index("ix_user_memory_source_session_id", "user_memory", ["source_session_id"])
        op.create_index(
            "ix_user_memory_user_active_importance",
            "user_memory",
            ["user_id", "is_active", "importance"],
        )

    if not _has_table(conn, "memory_events"):
        op.create_table(
            "memory_events",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "memory_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("user_memory.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("event_type", sa.TEXT(), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=True),
            sa.Column(
                "created_at",
                postgresql.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index("ix_memory_events_user_id", "memory_events", ["user_id"])
        op.create_index("ix_memory_events_memory_id", "memory_events", ["memory_id"])


def downgrade():
    conn = op.get_bind()

    if _has_table(conn, "memory_events"):
        op.drop_index("ix_memory_events_memory_id", table_name="memory_events")
        op.drop_index("ix_memory_events_user_id", table_name="memory_events")
        op.drop_table("memory_events")

    if _has_table(conn, "user_memory"):
        op.drop_index("ix_user_memory_user_active_importance", table_name="user_memory")
        op.drop_index("ix_user_memory_source_session_id", table_name="user_memory")
        op.drop_index("ix_user_memory_user_id", table_name="user_memory")
        op.drop_table("user_memory")

