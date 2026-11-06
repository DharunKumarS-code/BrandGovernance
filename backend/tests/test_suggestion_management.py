"""Phase 6, Module 5 tests: accept/dismiss endpoints, via the real HTTP API
-- authorisation, duplicate actions, concurrency, cross-org isolation, and
audit-log creation. Uses the same fakes/fixtures as the Phase 5 analysis
tests (no real Gemini calls)."""

import asyncio
from datetime import datetime, timezone

from bson import ObjectId

import app.services.analysis.orchestrator as orchestrator_module
from app.models import BrandFactCreate, OrganisationCreate, UserCreate, UserRole
from app.repositories import audit_log, brand_facts, organisations, users

from tests.ai_fakes import FakeEmbeddingProvider, FakeLLMProvider

PLANTED_MISTAKE_AD = "Nova Buds Pro deliver 12 hours of non-stop playback. Get them today!"


async def _seed_minimal_nova(org_id):
    await brand_facts.create(
        BrandFactCreate(
            organisation_id=org_id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours",
            valid_from=datetime(2025, 1, 15, tzinfo=timezone.utc), quote="8 hours of playback.",
        )
    )


async def _create_analysed_submission(api_client, headers, monkeypatch):
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Ad", "content": PLANTED_MISTAKE_AD})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)

    fake_llm = FakeLLMProvider(
        responses={
            "claims": {
                "claims": [
                    {"subject": "Nova Buds Pro", "attribute": "battery_life", "value": "12", "unit": "hours", "source_quote": "12 hours"},
                ]
            }
        }
    )
    monkeypatch.setattr(orchestrator_module, "get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: FakeEmbeddingProvider())
    await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)

    findings_resp = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    finding_id = findings_resp.json()[0]["id"]
    return sub_id, finding_id


# --- Accept / dismiss happy paths ------------------------------------------


async def test_accept_suggestion_records_decision_and_audit_log(api_client, demo_headers, monkeypatch):
    headers, org, user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    resp = await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/accept", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["finding"]["status"] == "accepted"
    assert body["finding"]["decided_by"] == str(user.id)
    assert body["finding"]["decided_at"] is not None
    assert "preview_content" in body  # may be None if no corrected_span exists yet, but the key is always present

    entries = await audit_log.list(organisation_id=org.id, filter={"entity_id": ObjectId(finding_id)}, limit=10)
    assert any(e.action == "finding_accepted" and str(e.actor_id) == str(user.id) for e in entries)


async def test_dismiss_suggestion_records_reason_and_audit_log(api_client, demo_headers, monkeypatch):
    headers, org, user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    resp = await api_client.post(
        f"/api/submissions/{sub_id}/findings/{finding_id}/dismiss", headers=headers, json={"reason": "Not applicable to this campaign."}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "dismissed"
    assert body["dismiss_reason"] == "Not applicable to this campaign."
    assert body["decided_by"] == str(user.id)

    entries = await audit_log.list(organisation_id=org.id, filter={"entity_id": ObjectId(finding_id)}, limit=10)
    assert any(e.action == "finding_dismissed" for e in entries)


async def test_dismiss_without_a_reason_is_allowed(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    resp = await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/dismiss", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["dismiss_reason"] is None


# --- Duplicate actions ------------------------------------------------------


async def test_duplicate_accept_is_rejected_with_409(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    first = await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/accept", headers=headers)
    assert first.status_code == 200

    second = await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/accept", headers=headers)
    assert second.status_code == 409

    # Dismissing an already-accepted finding is equally rejected -- the
    # decision, once made, is not silently overwritable by a different action.
    third = await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/dismiss", headers=headers)
    assert third.status_code == 409


# --- Unauthorised user -------------------------------------------------------


async def test_non_creator_cannot_accept_or_dismiss(api_client, demo_headers, monkeypatch):
    headers, org, _creator = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    other_user = await users.create(
        UserCreate(organisation_id=org.id, name="Not The Creator", email="not-creator@example.com", role=UserRole.REVIEWER)
    )
    other_headers = {"X-Organisation-Id": str(org.id), "X-User-Id": str(other_user.id)}

    accept_resp = await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/accept", headers=other_headers)
    assert accept_resp.status_code == 403

    dismiss_resp = await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/dismiss", headers=other_headers)
    assert dismiss_resp.status_code == 403


# --- Cross-organisation access ----------------------------------------------


async def test_cross_org_user_cannot_see_or_decide_findings(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    other_org = await organisations.create(OrganisationCreate(name="Other Org Suggestions"))
    other_user = await users.create(
        UserCreate(organisation_id=other_org.id, name="Outsider", email="outsider@example.com", role=UserRole.ADMIN)
    )
    other_headers = {"X-Organisation-Id": str(other_org.id), "X-User-Id": str(other_user.id)}

    assert (await api_client.get(f"/api/submissions/{sub_id}/findings/{finding_id}/evidence", headers=other_headers)).status_code == 404
    assert (await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/accept", headers=other_headers)).status_code == 404
    assert (await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/dismiss", headers=other_headers)).status_code == 404


# --- Concurrency -------------------------------------------------------------


async def test_concurrent_accept_and_dismiss_only_one_wins(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    accept_call = api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/accept", headers=headers)
    dismiss_call = api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/dismiss", headers=headers)
    accept_resp, dismiss_resp = await asyncio.gather(accept_call, dismiss_call)

    statuses = {accept_resp.status_code, dismiss_resp.status_code}
    assert statuses == {200, 409}  # exactly one of the two racing decisions wins

    final = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    decided = [f for f in final.json() if f["id"] == finding_id][0]
    assert decided["status"] in ("accepted", "dismissed")  # a real, single, consistent outcome


# --- Evidence / suggestion retrieval endpoints ------------------------------


async def test_evidence_and_suggestion_endpoints_round_trip(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    evidence_resp = await api_client.get(f"/api/submissions/{sub_id}/findings/{finding_id}/evidence", headers=headers)
    assert evidence_resp.status_code == 200
    assert evidence_resp.json()["status"] in ("supported", "contradicted", "insufficient", "needs_review")


# --- A finding cannot be reached through the wrong submission's URL --------


async def test_finding_from_another_submission_is_not_reachable(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id, finding_id = await _create_analysed_submission(api_client, headers, monkeypatch)

    # A second, unrelated submission in the SAME organisation.
    other_sub = await api_client.post("/api/submissions", headers=headers, json={"title": "Unrelated", "content": "Nothing interesting here."})
    other_sub_id = other_sub.json()["id"]

    resp = await api_client.get(f"/api/submissions/{other_sub_id}/findings/{finding_id}/evidence", headers=headers)
    assert resp.status_code == 404

    accept_resp = await api_client.post(f"/api/submissions/{other_sub_id}/findings/{finding_id}/accept", headers=headers)
    assert accept_resp.status_code == 404

    # No suggestion generated yet -> 404 on the plain GET.
    not_yet = await api_client.get(f"/api/submissions/{sub_id}/findings/{finding_id}/suggestion", headers=headers)
    assert not_yet.status_code == 404

    generate_resp = await api_client.post(f"/api/submissions/{sub_id}/findings/{finding_id}/suggestion", headers=headers)
    assert generate_resp.status_code == 200
    assert generate_resp.json()["correction"] is not None

    now_available = await api_client.get(f"/api/submissions/{sub_id}/findings/{finding_id}/suggestion", headers=headers)
    assert now_available.status_code == 200
