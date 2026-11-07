from app.core.config import settings
from app.core.security import verify_password
from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import organisations, users


async def _admin(email="first-admin@example.com"):
    org = await organisations.create(OrganisationCreate(name="Provisioning Org"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="First Admin", email=email, role=UserRole.ADMIN)
    )
    return org, user


def _payload(org, user, password="a sufficiently long password"):
    return {"organisation_id": str(org.id), "user_id": str(user.id), "password": password}


def _headers(secret="temporary-bootstrap-secret-for-tests"):
    return {"X-Admin-Bootstrap-Secret": secret}


async def test_admin_provisioning_sets_bcrypt_hash_and_enables_login(api_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_secret", "temporary-bootstrap-secret-for-tests")
    org, user = await _admin()

    response = await api_client.post("/api/auth/admin/provision", headers=_headers(), json=_payload(org, user))

    assert response.status_code == 204
    stored = await users.get(user.id, organisation_id=org.id)
    assert stored.password_hash and stored.password_hash != "a sufficiently long password"
    assert verify_password("a sufficiently long password", stored.password_hash)
    assert response.content == b""
    login = await api_client.post(
        "/api/auth/login", json={"email": user.email, "password": "a sufficiently long password"}
    )
    assert login.status_code == 200
    assert "password_hash" not in login.text


async def test_admin_provisioning_rejects_incorrect_or_missing_secret(api_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_secret", "temporary-bootstrap-secret-for-tests")
    org, user = await _admin()
    for headers in ({}, _headers("wrong-secret")):
        response = await api_client.post("/api/auth/admin/provision", headers=headers, json=_payload(org, user))
        assert response.status_code == 401
    stored = await users.get(user.id, organisation_id=org.id)
    assert stored.password_hash is None


async def test_admin_provisioning_rejects_non_admin_and_existing_password(api_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_secret", "temporary-bootstrap-secret-for-tests")
    org = await organisations.create(OrganisationCreate(name="Provisioning Role Org"))
    creator = await users.create(
        UserCreate(organisation_id=org.id, name="Creator", email="creator-provision@example.com", role=UserRole.CREATOR)
    )
    response = await api_client.post("/api/auth/admin/provision", headers=_headers(), json=_payload(org, creator))
    assert response.status_code == 409

    existing = await users.create(
        UserCreate(organisation_id=org.id, name="Existing", email="existing-provision@example.com", role=UserRole.ADMIN,
                   password_hash="already-set-hash")
    )
    response = await api_client.post("/api/auth/admin/provision", headers=_headers(), json=_payload(org, existing))
    assert response.status_code == 409
    stored = await users.get(existing.id, organisation_id=org.id)
    assert stored.password_hash == "already-set-hash"


async def test_admin_provisioning_is_one_time_and_concurrency_safe(api_client, monkeypatch):
    import asyncio

    monkeypatch.setattr(settings, "admin_bootstrap_secret", "temporary-bootstrap-secret-for-tests")
    org, user = await _admin("concurrent-admin@example.com")
    payload = _payload(org, user)
    first = await api_client.post("/api/auth/admin/provision", headers=_headers(), json=payload)
    repeated = await api_client.post("/api/auth/admin/provision", headers=_headers(), json=payload)
    assert first.status_code == 204
    assert repeated.status_code == 409

    other_org, other_user = await _admin("race-admin@example.com")
    race_payload = _payload(other_org, other_user)
    responses = await asyncio.gather(*[
        api_client.post("/api/auth/admin/provision", headers=_headers(), json=race_payload)
        for _ in range(2)
    ])
    assert sorted(response.status_code for response in responses) == [204, 409]
    stored = await users.get(other_user.id, organisation_id=other_org.id)
    assert stored.password_hash and verify_password("a sufficiently long password", stored.password_hash)


async def test_admin_provisioning_cannot_target_another_organisation(api_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_secret", "temporary-bootstrap-secret-for-tests")
    org, user = await _admin()
    other_org = await organisations.create(OrganisationCreate(name="Wrong Provisioning Org"))
    response = await api_client.post("/api/auth/admin/provision", headers=_headers(), json=_payload(other_org, user))
    assert response.status_code == 409
    assert (await users.get(user.id, organisation_id=org.id)).password_hash is None


async def test_admin_provisioning_does_not_echo_rejected_password(api_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_bootstrap_secret", "temporary-bootstrap-secret-for-tests")
    org, user = await _admin("invalid-password@example.com")
    rejected_password = "too-short"
    response = await api_client.post(
        "/api/auth/admin/provision", headers=_headers(),
        json=_payload(org, user, password=rejected_password),
    )
    assert response.status_code == 400
    assert rejected_password not in response.text
    assert "input" not in response.text
