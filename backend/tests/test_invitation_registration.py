"""Tests for invitation-only password and OIDC account creation."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from jose import jwt
import pytest

from api import auth
from core.security import create_oauth_state
from db.models.registration_invite import RegistrationInvite
from services.auth import invitations


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return self

    def first(self):
        return self.value


class _FakeSession:
    def __init__(self, results):
        self.results = list(results)
        self.added = []
        self.committed = False

    async def execute(self, _statement):
        return _ScalarResult(self.results.pop(0))

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid4()

    async def commit(self):
        self.committed = True


def _invite(email="alice@example.com", token="one-time-token", *, hours=1):
    return RegistrationInvite(
        email=email,
        token_hash=invitations.hash_invite_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=hours),
    )


@pytest.mark.unit
def test_invite_validation_rejects_expired_used_and_wrong_email():
    now = datetime.now(timezone.utc)
    expired = _invite(hours=-1)
    used = _invite()
    used.used_at = now
    wrong_email = _invite(email="other@example.com")

    for invite in (expired, used, wrong_email):
        with pytest.raises(HTTPException) as exc_info:
            invitations.validate_invite(invite, "alice@example.com", now=now)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == invitations.INVITE_ERROR


@pytest.mark.unit
@pytest.mark.asyncio
async def test_password_signup_requires_an_invitation(monkeypatch):
    monkeypatch.setattr(invitations, "REGISTRATION_MODE", "invite")
    session = _FakeSession([])

    with pytest.raises(HTTPException) as exc_info:
        await auth.signup(
            auth.SignUpForm(
                email="alice@example.com",
                password="password123",
                display_name="Alice",
            ),
            session,
        )

    assert exc_info.value.status_code == 403
    assert session.added == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_password_signup_consumes_matching_invitation(monkeypatch):
    monkeypatch.setattr(invitations, "REGISTRATION_MODE", "invite")
    invite = _invite()
    session = _FakeSession([invite, None])

    response = await auth.signup(
        auth.SignUpForm(
            email=" Alice@Example.com ",
            password="password123",
            display_name="Alice",
            invite_token="one-time-token",
        ),
        session,
    )

    user = session.added[0]
    assert response.status_code == 200
    assert user.email == "alice@example.com"
    assert invite.used_by_id == user.id
    assert invite.used_at is not None
    assert session.committed is True


@pytest.mark.unit
def test_oauth_state_contains_only_the_invitation_hash():
    token = "one-time-token"
    state = create_oauth_state(
        "test",
        "http://localhost:3000/map",
        invite_hash=invitations.hash_invite_token(token),
    )
    payload = jwt.get_unverified_claims(state)

    assert payload["invite_hash"] == invitations.hash_invite_token(token)
    assert token not in state


class _UserInfoResponse:
    def json(self):
        return {
            "sub": "oidc-user-1",
            "email": "alice@example.com",
            "email_verified": True,
            "name": "Alice",
        }


class _FakeOAuthClient:
    def __init__(self, *_args, **_kwargs):
        self.token = None

    async def fetch_token(self, _endpoint, code):
        assert code == "authorization-code"
        return {"access_token": "access-token"}

    async def get(self, _endpoint):
        return _UserInfoResponse()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_new_oidc_account_cannot_bypass_invitation(monkeypatch):
    monkeypatch.setattr(invitations, "REGISTRATION_MODE", "invite")
    monkeypatch.setattr(auth, "AsyncOAuth2Client", _FakeOAuthClient)
    monkeypatch.setattr(auth, "_validate_redirect", lambda redirect: redirect)
    monkeypatch.setattr(
        auth,
        "_get_provider_config",
        lambda _name: {
            "client_id": "client",
            "client_secret": "secret",
            "scopes": "openid email profile",
            "issuer": "https://issuer.example",
        },
    )

    async def metadata(_client, _issuer):
        return {
            "token_endpoint": "https://issuer.example/token",
            "userinfo_endpoint": "https://issuer.example/userinfo",
        }

    monkeypatch.setattr(auth, "_fetch_oidc_metadata", metadata)
    state = create_oauth_state("test", "http://localhost:3000/map")
    session = _FakeSession([None, None])

    with pytest.raises(HTTPException) as exc_info:
        await auth.oidc_callback(
            request=None,
            code="authorization-code",
            state=state,
            db=session,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == invitations.INVITE_ERROR
    assert session.added == []
