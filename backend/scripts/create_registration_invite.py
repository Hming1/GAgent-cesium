"""Create a one-time registration invitation from the command line."""

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from core.config import FRONTEND_BASE_URL
from core.asyncio_compat import configure_windows_selector_event_loop
from db.models.registration_invite import RegistrationInvite
from db.session import AsyncSessionLocal
from services.auth.invitations import (
    generate_invite_token,
    hash_invite_token,
    normalize_email,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="Email address authorized to register")
    parser.add_argument(
        "--hours",
        type=int,
        default=168,
        help="Invitation lifetime in hours (default: 168 / 7 days)",
    )
    parser.add_argument(
        "--base-url",
        default=FRONTEND_BASE_URL,
        help="Frontend origin used to build the invitation URL",
    )
    return parser.parse_args()


async def create_invitation(email: str, hours: int, base_url: str) -> str:
    if AsyncSessionLocal is None:
        raise RuntimeError("DATABASE_URL must be configured")
    normalized_email = normalize_email(email)
    if "@" not in normalized_email:
        raise ValueError("A valid email address is required")
    if hours <= 0:
        raise ValueError("--hours must be greater than zero")

    token = generate_invite_token()
    invite = RegistrationInvite(
        email=normalized_email,
        token_hash=hash_invite_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=hours),
    )
    async with AsyncSessionLocal() as session:
        session.add(invite)
        await session.commit()

    return f"{base_url.rstrip('/')}/signup?invite={quote(token, safe='')}"


async def main() -> None:
    args = parse_args()
    invitation_url = await create_invitation(args.email, args.hours, args.base_url)
    print(invitation_url)


if __name__ == "__main__":
    configure_windows_selector_event_loop()
    asyncio.run(main())
