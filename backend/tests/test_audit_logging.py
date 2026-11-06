"""Phase 7 Stage 2 follow-up: focused audit-log correctness checks.

Check 1 found that all 8 required dashboard-activity events (content
creation incl. PDF upload, draft submission, AI analysis, resubmission,
approval, rejection, changes-requested) were ALREADY logged correctly
(added across Stage 1/Stage 2) -- so there is no new event type to add
here. This file instead covers the events that weren't yet directly
asserted against the audit_log collection (as opposed to indirectly, via
the dashboard's recent_activity feed), plus the two cross-cutting
correctness rules from this check: a failed/rejected request must never
produce a successful-action audit entry, and a failure in the audit write
itself must never make an already-successful business action look like
it failed to the caller.
"""

import fitz

from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import audit_log, organisations, users

import app.routers.submissions as submissions_router


def _make_pdf_bytes(pages_text: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages_text:
        doc.new_page().insert_text((50, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


async def _reviewer(org_id):
    return await users.create(
        UserCreate(organisation_id=org_id, name="Audit Reviewer", email="audit-reviewer@example.com", role=UserRole.REVIEWER)
    )


def _headers(org_id, user_id):
    return {"X-Organisation-Id": str(org_id), "X-User-Id": str(user_id)}


# --- Content creation (text) -------------------------------------------------


async def test_submission_created_audit_entry_is_correct_for_text_content(api_client, demo_headers):
    from bson import ObjectId

    headers, org, creator = demo_headers
    resp = await api_client.post("/api/submissions", headers=headers, json={"title": "Audit Text Ad", "content": "x"})
    sub_id = resp.json()["id"]

    entries = await audit_log.list(organisation_id=org.id, filter={"action": "submission_created", "entity_id": ObjectId(sub_id)}, limit=10)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.organisation_id == org.id
    assert entry.entity_id == ObjectId(sub_id)
    assert entry.actor_id == creator.id


# --- Content creation (PDF upload) ------------------------------------------


async def test_submission_created_audit_entry_is_correct_for_pdf_upload(api_client, demo_headers):
    headers, org, creator = demo_headers
    pdf_bytes = _make_pdf_bytes(["Audit PDF ad copy."])
    resp = await api_client.post(
        "/api/submissions/upload", headers=headers,
        files={"file": ("ad.pdf", pdf_bytes, "application/pdf")}, data={"title": "Audit PDF Ad"},
    )
    assert resp.status_code == 201, resp.text
    sub_id = resp.json()["id"]

    from bson import ObjectId

    entries = await audit_log.list(organisation_id=org.id, filter={"action": "submission_created", "entity_id": ObjectId(sub_id)}, limit=10)
    assert len(entries) == 1
    assert entries[0].actor_id == creator.id


# --- Draft submission + resubmission ----------------------------------------


async def test_submission_submitted_audit_entry_is_correct(api_client, demo_headers):
    from bson import ObjectId

    headers, org, creator = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Submit Ad", "content": "x"})
    sub_id = created.json()["id"]

    resp = await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    assert resp.status_code == 200

    entries = await audit_log.list(organisation_id=org.id, filter={"action": "submission_submitted", "entity_id": ObjectId(sub_id)}, limit=10)
    assert len(entries) == 1
    assert entries[0].organisation_id == org.id
    assert entries[0].actor_id == creator.id


async def test_submission_resubmitted_audit_entry_is_correct(api_client, demo_headers):
    from bson import ObjectId

    headers, org, creator = demo_headers
    reviewer = await _reviewer(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)

    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Resubmit Ad", "content": "v1"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{sub_id}/request-changes", headers=reviewer_headers, json={"comment": "fix"})
    await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2"})

    resp = await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    assert resp.status_code == 200

    entries = await audit_log.list(organisation_id=org.id, filter={"action": "submission_resubmitted", "entity_id": ObjectId(sub_id)}, limit=10)
    assert len(entries) == 1  # the FIRST submit logged "submission_submitted", not this one
    first_submit = await audit_log.list(organisation_id=org.id, filter={"action": "submission_submitted", "entity_id": ObjectId(sub_id)}, limit=10)
    assert len(first_submit) == 1


# --- AI analysis completed ---------------------------------------------------


async def test_submission_analyzed_audit_entry_is_correct(api_client, demo_headers, monkeypatch):
    from bson import ObjectId

    from tests.ai_fakes import FakeEmbeddingProvider, FakeLLMProvider

    headers, org, creator = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Analyze Ad", "content": "x"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)

    import app.services.analysis.orchestrator as orchestrator_module

    monkeypatch.setattr(orchestrator_module, "get_llm_provider", lambda: FakeLLMProvider())
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: FakeEmbeddingProvider())
    resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp.status_code == 200

    entries = await audit_log.list(organisation_id=org.id, filter={"action": "submission_analyzed", "entity_id": ObjectId(sub_id)}, limit=10)
    assert len(entries) == 1
    assert entries[0].actor_id == creator.id
    assert entries[0].details.get("findings_count") == resp.json()["findings_count"]


async def test_failed_analysis_does_not_create_an_audit_entry(api_client, demo_headers, monkeypatch):
    from bson import ObjectId

    from app.core.config import settings

    headers, org, creator = demo_headers
    monkeypatch.setattr(settings, "analysis_max_content_chars", 2)
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Too Long Ad", "content": "way more than two characters"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)

    resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp.status_code == 413  # the analysis itself was rejected, never ran

    entries = await audit_log.list(organisation_id=org.id, filter={"action": "submission_analyzed", "entity_id": ObjectId(sub_id)}, limit=10)
    assert entries == []  # no "analysis completed" entry for an analysis that never completed


# --- Critical rule: a rejected/duplicate request must not log success ------


async def test_duplicate_review_decision_does_not_create_a_second_audit_entry(api_client, demo_headers):
    from bson import ObjectId

    headers, org, creator = demo_headers
    reviewer = await _reviewer(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)

    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Dup Decision Ad", "content": "x"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)

    first = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers)
    assert first.status_code == 200
    duplicate = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers)
    assert duplicate.status_code == 409  # rejected -- must not claim a second approval happened

    entries = await audit_log.list(organisation_id=org.id, filter={"action": "submission_approved", "entity_id": ObjectId(sub_id)}, limit=10)
    assert len(entries) == 1  # exactly one real decision, not two


# --- Critical rule: an audit-write failure must not falsely fail a real success


async def test_audit_write_failure_does_not_fail_the_business_action(api_client, demo_headers, monkeypatch):
    """If _record_audit's own write throws (simulated here), the endpoint
    must still return its normal success response -- the submission really
    was created, and reporting a 500 would contradict that."""
    headers, org, creator = demo_headers

    async def _boom(entry):
        raise RuntimeError("simulated audit_log write failure")

    monkeypatch.setattr(submissions_router.audit_log, "create", _boom)

    resp = await api_client.post("/api/submissions", headers=headers, json={"title": "Resilient Ad", "content": "x"})
    assert resp.status_code == 201, resp.text  # NOT a 500, despite the audit write failing underneath

    # The submission itself really was created, confirming this wasn't a
    # false success either -- it actually committed.
    get_resp = await api_client.get(f"/api/submissions/{resp.json()['id']}", headers=headers)
    assert get_resp.status_code == 200


# --- Organisation isolation of audit entries --------------------------------


async def test_audit_entries_are_organisation_scoped_and_never_cross_link(api_client, demo_headers):
    from bson import ObjectId

    headers, org_a, _creator_a = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Org A Audit Ad", "content": "x"})
    sub_id = created.json()["id"]

    org_b = await organisations.create(OrganisationCreate(name="Audit Isolation Org B"))
    user_b = await users.create(UserCreate(organisation_id=org_b.id, name="B User", email="audit-isolation-b@example.com", role=UserRole.ADMIN))

    # The exact same entity_id, queried under org B's scope, must return nothing.
    entries_under_b = await audit_log.list(organisation_id=org_b.id, filter={"entity_id": ObjectId(sub_id)}, limit=10)
    assert entries_under_b == []
