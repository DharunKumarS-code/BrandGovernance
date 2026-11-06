"""Phase 9 Stage 2: JWT auth -- login, token verification, hybrid
backward-compatibility with the existing demo-header mechanism, org
isolation under JWT, and self-review prevention via JWT identity."""

import time

from jose import jwt as jose_jwt

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import organisations, users


async def _org_with_password_user(password: str = "correct horse battery staple", role=UserRole.ADMIN):
    org = await organisations.create(OrganisationCreate(name="Auth Test Org"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Auth User", email="auth-user@example.com", role=role, password_hash=hash_password(password))
    )
    return org, user


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- password hashing --------------------------------------------------


def test_password_hash_roundtrip():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h)
    assert not verify_password("wrong", h)


# --- login ---------------------------------------------------------------


async def test_login_success_returns_token_and_user(api_client):
    org, user = await _org_with_password_user()
    resp = await api_client.post("/api/auth/login", json={"email": "auth-user@example.com", "password": "correct horse battery staple"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["id"] == str(user.id)
    assert body["user"]["organisation_id"] == str(org.id)
    assert "access_token" in body and body["access_token"]


async def test_login_wrong_password_rejected(api_client):
    await _org_with_password_user()
    resp = await api_client.post("/api/auth/login", json={"email": "auth-user@example.com", "password": "nope"})
    assert resp.status_code == 401


async def test_login_unknown_email_rejected(api_client):
    resp = await api_client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert resp.status_code == 401


async def test_login_user_without_password_set_is_rejected_not_crashed(api_client):
    org = await organisations.create(OrganisationCreate(name="No Password Org"))
    await users.create(UserCreate(organisation_id=org.id, name="No Pw", email="no-password@example.com", role=UserRole.ADMIN))
    resp = await api_client.post("/api/auth/login", json={"email": "no-password@example.com", "password": "anything"})
    assert resp.status_code == 401  # never a 500 from calling verify() on a None hash


# --- JWT authenticates existing, UNMODIFIED endpoints ---------------------


async def test_jwt_token_authenticates_existing_endpoint_with_no_demo_headers(api_client):
    org, user = await _org_with_password_user()
    login = await api_client.post("/api/auth/login", json={"email": "auth-user@example.com", "password": "correct horse battery staple"})
    token = login.json()["access_token"]

    resp = await api_client.get("/api/dashboard/summary", headers=_bearer(token))
    assert resp.status_code == 200, resp.text  # no X-Organisation-Id/X-User-Id sent at all


async def test_jwt_identity_wins_over_spoofed_demo_headers(api_client):
    org_a, user_a = await _org_with_password_user(password="pw-a")
    org_b, user_b = await _org_with_password_user(password="pw-b")
    token, _exp = create_access_token(user_id=str(user_a.id), organisation_id=str(org_a.id), role="admin")

    # Attacker-controlled headers claim org_b -- must be ignored outright
    # once a Bearer token is present.
    spoofed_headers = {**_bearer(token), "X-Organisation-Id": str(org_b.id), "X-User-Id": str(user_b.id)}
    resp = await api_client.get("/api/auth/me", headers=spoofed_headers)
    assert resp.status_code == 200
    assert resp.json()["organisation_id"] == str(org_a.id)  # token wins, not the spoofed headers


async def test_invalid_token_rejected(api_client):
    resp = await api_client.get("/api/dashboard/summary", headers=_bearer("not-a-real-token"))
    assert resp.status_code == 401


async def test_expired_token_rejected(api_client):
    org, user = await _org_with_password_user()
    now = int(time.time())
    expired = jose_jwt.encode(
        {"sub": str(user.id), "org": str(org.id), "role": "admin", "iat": now - 1000, "exp": now - 500},
        settings.jwt_secret_key, algorithm=settings.jwt_algorithm,
    )
    resp = await api_client.get("/api/dashboard/summary", headers=_bearer(expired))
    assert resp.status_code == 401


# --- production lockdown (require_jwt_auth) -------------------------------


async def test_require_jwt_auth_rejects_demo_headers_when_enabled(api_client, demo_headers, monkeypatch):
    headers, _org, _user = demo_headers
    monkeypatch.setattr(settings, "require_jwt_auth", True)
    resp = await api_client.get("/api/dashboard/summary", headers=headers)  # demo headers only, no token
    assert resp.status_code == 401


async def test_require_jwt_auth_still_accepts_valid_token(api_client, monkeypatch):
    org, user = await _org_with_password_user()
    token, _exp = create_access_token(user_id=str(user.id), organisation_id=str(org.id), role="admin")
    monkeypatch.setattr(settings, "require_jwt_auth", True)
    resp = await api_client.get("/api/dashboard/summary", headers=_bearer(token))
    assert resp.status_code == 200


# --- demo-endpoint gating + no password leakage ---------------------------


async def test_demo_endpoints_gated_when_disabled(api_client, monkeypatch):
    monkeypatch.setattr(settings, "enable_demo_endpoints", False)
    resp = await api_client.get("/api/demo/organisations")
    assert resp.status_code == 404


async def test_demo_user_listing_never_exposes_password_hash(api_client):
    org, user = await _org_with_password_user()
    resp = await api_client.get(f"/api/demo/organisations/{org.id}/users")
    assert resp.status_code == 200
    assert all("password_hash" not in u for u in resp.json())


# --- self-review prevention still holds under JWT identity ----------------


async def test_self_review_still_prevented_via_jwt_identity(api_client):
    org = await organisations.create(OrganisationCreate(name="JWT Self Review Org"))
    reviewer = await users.create(
        UserCreate(organisation_id=org.id, name="Reviewer", email="jwt-reviewer@example.com", role=UserRole.REVIEWER, password_hash=hash_password("pw"))
    )
    token, _exp = create_access_token(user_id=str(reviewer.id), organisation_id=str(org.id), role="reviewer")

    created = await api_client.post("/api/submissions", headers=_bearer(token), json={"title": "Own Ad", "content": "x"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=_bearer(token))

    resp = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=_bearer(token))
    assert resp.status_code == 403  # creator == reviewer identity from the token -- still blocked
