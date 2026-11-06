"""Demo organisation/user context validation (see app/core/demo_context.py)."""

from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import organisations, users


async def test_dashboard_requires_headers(api_client):
    resp = await api_client.get("/api/dashboard/summary")
    assert resp.status_code == 422  # missing required headers


async def test_dashboard_rejects_unknown_organisation(api_client):
    from bson import ObjectId

    fake_org = str(ObjectId())
    fake_user = str(ObjectId())
    resp = await api_client.get(
        "/api/dashboard/summary", headers={"X-Organisation-Id": fake_org, "X-User-Id": fake_user}
    )
    assert resp.status_code == 404


async def test_dashboard_rejects_user_not_in_organisation(api_client):
    org_a = await organisations.create(OrganisationCreate(name="Org A"))
    org_b = await organisations.create(OrganisationCreate(name="Org B"))
    user_in_b = await users.create(
        UserCreate(organisation_id=org_b.id, name="B User", email="b@example.com", role=UserRole.ADMIN)
    )
    resp = await api_client.get(
        "/api/dashboard/summary",
        headers={"X-Organisation-Id": str(org_a.id), "X-User-Id": str(user_in_b.id)},
    )
    assert resp.status_code == 403


async def test_dashboard_rejects_malformed_ids(api_client):
    resp = await api_client.get(
        "/api/dashboard/summary", headers={"X-Organisation-Id": "not-an-id", "X-User-Id": "also-not-an-id"}
    )
    assert resp.status_code == 400


async def test_dashboard_accepts_valid_matching_context(api_client, demo_headers):
    # Phase 7 Stage 2 expanded the dashboard response (submissions/issues/
    # reviews/recent_activity) -- see tests/test_dashboard_stats.py for
    # dedicated coverage of those. This test only needs to confirm the
    # endpoint still accepts a valid context and the original Phase 1-4
    # governance counts are still present and correct for a brand-new org.
    headers, _org, _user = demo_headers
    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["guideline_docs"] == 0
    assert body["brand_facts"] == 0
    assert body["terminology"] == 0
    assert body["claim_policies"] == 0
    assert body["assets"] == 0
    assert body["submissions"]["total"] == 0
    assert body["reviews"]["completed"] == 0
    assert body["recent_activity"] == []
