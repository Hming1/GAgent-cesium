"""Add one-time registration invitations."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260724_registration_invites"
down_revision = "20260626_add_agent_audit"
branch_labels = None
depends_on = None


def _has_table(conn, table_name: str) -> bool:
    return sa.inspect(conn).has_table(table_name)


def upgrade():
    conn = op.get_bind()
    if _has_table(conn, "registration_invites"):
        return

    op.create_table(
        "registration_invites",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.TEXT(), nullable=False),
        sa.Column("token_hash", sa.TEXT(), nullable=False, unique=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "used_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_registration_invites_email", "registration_invites", ["email"])
    op.create_index(
        "ix_registration_invites_expires_at",
        "registration_invites",
        ["expires_at"],
    )


def downgrade():
    conn = op.get_bind()
    if _has_table(conn, "registration_invites"):
        op.drop_index(
            "ix_registration_invites_expires_at",
            table_name="registration_invites",
        )
        op.drop_index("ix_registration_invites_email", table_name="registration_invites")
        op.drop_table("registration_invites")
