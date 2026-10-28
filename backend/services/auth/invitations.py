"""Creation and validation helpers for registration invitations."""

from datetime import datetime, timezone
import hashlib
import secrets

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import REGISTRATION_MODE
from db.models.registration_invite import RegistrationInvite


INVITE_ERROR = "A valid invitation for this email address is required"


def normalize_email(email: str) -> str:
    """Normalize an email for account and invitation comparisons."""
    return email.strip().casefold()


def generate_invite_token() -> str:
    """Return a cryptographically secure invitation token."""
    return secrets.token_urlsafe(32)


def hash_invite_token(token: str) -> str:
    """Hash a token so the database never stores the usable secret."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _deny_invitation() -> None:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=INVITE_ERROR)


def validate_invite(
    invite: RegistrationInvite | None,
    email: str,
    *,
    now: datetime | None = None,
) -> RegistrationInvite:
    """Validate invitation state without revealing why validation failed."""
    current_time = now or datetime.now(timezone.utc)
    if (
        invite is None
        or invite.used_at is not None
        or invite.expires_at <= current_time
        or normalize_email(invite.email) != normalize_email(email)
    ):
        _deny_invitation()
    return invite


async def authorize_registration(
    db: AsyncSession,
    email: str,
    *,
    invite_token: str | None = None,
    invite_hash: str | None = None,
) -> RegistrationInvite | None:
    """Authorize a new account according to the configured registration mode.

    The invitation row is locked until the caller commits or rolls back, which
    prevents a single token from being consumed by concurrent registrations.
    """
    if REGISTRATION_MODE == "open":
        return None
    if REGISTRATION_MODE == "closed":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="New account registration is closed",
        )

    token_hash = invite_hash
    if invite_token:
        token_hash = hash_invite_token(invite_token)
    if not token_hash:
        _deny_invitation()

    result = await db.execute(
        select(RegistrationInvite).filter_by(token_hash=token_hash).with_for_update()
    )
    invite = result.scalars().first()
    return validate_invite(invite, email)


def consume_invite(invite: RegistrationInvite | None, user_id) -> None:
    """Mark an invitation as consumed by a newly created user."""
    if invite is None:
        return
    invite.used_at = datetime.now(timezone.utc)
    invite.used_by_id = user_id
