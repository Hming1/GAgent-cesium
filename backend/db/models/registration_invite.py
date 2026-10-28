"""ORM model for one-time registration invitations."""

from sqlalchemy import Column, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import TEXT, TIMESTAMP, UUID

from db.base import Base


class RegistrationInvite(Base):
    """A single-use invitation authorizing creation of one user account."""

    __tablename__ = "registration_invites"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email = Column(TEXT, nullable=False)
    token_hash = Column(TEXT, nullable=False, unique=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used_at = Column(TIMESTAMP(timezone=True), nullable=True)
    used_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        Index("ix_registration_invites_email", "email"),
        Index("ix_registration_invites_expires_at", "expires_at"),
    )
