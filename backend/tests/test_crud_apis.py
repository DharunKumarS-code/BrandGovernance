"""Brand facts, terminology and claim policies CRUD + cross-org isolation,
exercised through the real HTTP API."""

from datetime import datetime, timezone

from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import organisations, users


async def _other_org_headers():
    org = await organisations.create(OrganisationCreate(name="Other Org CRUD"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Other", email="other-crud@example.com", role=UserRole.ADMIN)
    )
    return {"X-Organisation-Id": str(org.id), "X-User-Id": str(user.id)}


async def test_brand_fact_crud(api_client, demo_headers):
    headers, org, _user = demo_headers
    create_resp = await api_client.post(
        "/api/brand-facts",
        headers=headers,
        json={
            "organisation_id": str(org.id),  # server overwrites this from context anyway
            "subject": "Widget",
            "attribute": "price",
            "value": "10",
            "unit": "USD",
            "valid_from": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
            "valid_to": None,
            "source_doc_id": str(org.id),
            "page": 1,
            "quote": "Widget costs $10.",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    fact_id = create_resp.json()["id"]
    assert create_resp.json()["organisation_id"] == str(org.id)

    list_resp = await api_client.get("/api/brand-facts", headers=headers)
    assert any(f["id"] == fact_id for f in list_resp.json())

    get_resp = await api_client.get(f"/api/brand-facts/{fact_id}", headers=headers)
    assert get_resp.status_code == 200

    update_resp = await api_client.patch(f"/api/brand-facts/{fact_id}", headers=headers, json={"value": "12"})
    assert update_resp.status_code == 200
    assert update_resp.json()["value"] == "12"

    delete_resp = await api_client.delete(f"/api/brand-facts/{fact_id}", headers=headers)
    assert delete_resp.status_code == 204
    assert (await api_client.get(f"/api/brand-facts/{fact_id}", headers=headers)).status_code == 404


async def test_brand_fact_cross_org_isolation(api_client, demo_headers):
    headers_a, org, _user = demo_headers
    headers_b = await _other_org_headers()

    create_resp = await api_client.post(
        "/api/brand-facts",
        headers=headers_a,
        json={
            "organisation_id": str(org.id),
            "subject": "Secret",
            "attribute": "x",
            "value": "1",
            "valid_from": datetime(2025, 1, 1, tzinfo=timezone.utc).isoformat(),
            "source_doc_id": str(org.id),
            "page": 1,
            "quote": "secret",
        },
    )
    fact_id = create_resp.json()["id"]

    assert (await api_client.get(f"/api/brand-facts/{fact_id}", headers=headers_b)).status_code == 404
    assert (await api_client.patch(f"/api/brand-facts/{fact_id}", headers=headers_b, json={"value": "999"})).status_code == 404
    assert (await api_client.delete(f"/api/brand-facts/{fact_id}", headers=headers_b)).status_code == 404

    unaffected = await api_client.get(f"/api/brand-facts/{fact_id}", headers=headers_a)
    assert unaffected.status_code == 200
    assert unaffected.json()["value"] == "1"


async def test_terminology_crud(api_client, demo_headers):
    headers, org, _user = demo_headers
    create_resp = await api_client.post(
        "/api/terminology",
        headers=headers,
        json={"organisation_id": str(org.id), "preferred_term": "Affordable", "banned_variants": ["Cheap"], "reason": "tone"},
    )
    assert create_resp.status_code == 201
    term_id = create_resp.json()["id"]

    update_resp = await api_client.patch(f"/api/terminology/{term_id}", headers=headers, json={"reason": "updated"})
    assert update_resp.json()["reason"] == "updated"

    assert (await api_client.delete(f"/api/terminology/{term_id}", headers=headers)).status_code == 204


async def test_terminology_cross_org_isolation(api_client, demo_headers):
    headers_a, org, _user = demo_headers
    headers_b = await _other_org_headers()
    created = await api_client.post(
        "/api/terminology",
        headers=headers_a,
        json={"organisation_id": str(org.id), "preferred_term": "X", "banned_variants": ["Y"], "reason": "r"},
    )
    term_id = created.json()["id"]
    assert (await api_client.get(f"/api/terminology/{term_id}", headers=headers_b)).status_code == 404
    assert (await api_client.delete(f"/api/terminology/{term_id}", headers=headers_b)).status_code == 404


async def test_claim_policy_crud(api_client, demo_headers):
    headers, org, _user = demo_headers
    create_resp = await api_client.post(
        "/api/claim-policies",
        headers=headers,
        json={"organisation_id": str(org.id), "pattern": "best", "status": "needs_evidence", "required_disclaimer": None},
    )
    assert create_resp.status_code == 201
    policy_id = create_resp.json()["id"]

    update_resp = await api_client.patch(
        f"/api/claim-policies/{policy_id}", headers=headers, json={"status": "banned"}
    )
    assert update_resp.json()["status"] == "banned"

    assert (await api_client.delete(f"/api/claim-policies/{policy_id}", headers=headers)).status_code == 204


async def test_claim_policy_cross_org_isolation(api_client, demo_headers):
    headers_a, org, _user = demo_headers
    headers_b = await _other_org_headers()
    created = await api_client.post(
        "/api/claim-policies",
        headers=headers_a,
        json={"organisation_id": str(org.id), "pattern": "guaranteed", "status": "banned"},
    )
    policy_id = created.json()["id"]
    assert (await api_client.get(f"/api/claim-policies/{policy_id}", headers=headers_b)).status_code == 404
    assert (await api_client.patch(f"/api/claim-policies/{policy_id}", headers=headers_b, json={"status": "approved"})).status_code == 404
