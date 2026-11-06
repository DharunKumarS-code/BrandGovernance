"""Phase 7, Stage 1 tests: reviewer approve/reject/request-changes, via the
real HTTP API. No real Gemini calls involved anywhere in this file (the
reviewer workflow doesn't touch AI analysis at all), consistent with the
existing conftest.py GEMINI_API_KEY="" isolation.
"""

import asyncio

from bson import ObjectId

from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import audit_log, organisations, users


async def _reviewer_and_admin(org_id):
    reviewer = await users.create(
        UserCreate(organisation_id=org_id, name="Reviewer", email="reviewer-test@example.com", role=UserRole.REVIEWER)
    )
    admin = await users.create(
        UserCreate(organisation_id=org_id, name="Admin", email="admin-test@example.com", role=UserRole.ADMIN)
    )
    return reviewer, admin


def _headers(org_id, user_id):
    return {"X-Organisation-Id": str(org_id), "X-User-Id": str(user_id)}


async def _create_pending_submission(api_client, creator_headers, content="Ad copy for review."):
    created = await api_client.post("/api/submissions", headers=creator_headers, json={"title": "Review Me", "content": content})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=creator_headers)
    return sub_id


# --- Happy paths -------------------------------------------------------------


async def test_reviewer_can_approve(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    sub_id = await _create_pending_submission(api_client, headers)
    reviewer_headers = _headers(org.id, reviewer.id)

    resp = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers, json={"comment": "Looks good."})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["submission"]["status"] == "approved"
    assert body["review"]["decision"] == "approved"
    assert body["review"]["reviewer_id"] == str(reviewer.id)
    assert body["review"]["comment"] == "Looks good."

    entries = await audit_log.list(organisation_id=org.id, filter={"entity_id": ObjectId(sub_id)}, limit=10)
    assert any(e.action == "submission_approved" and str(e.actor_id) == str(reviewer.id) for e in entries)


async def test_reviewer_can_reject_with_comment(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    sub_id = await _create_pending_submission(api_client, headers)
    reviewer_headers = _headers(org.id, reviewer.id)

    resp = await api_client.post(f"/api/submissions/{sub_id}/reject", headers=reviewer_headers, json={"comment": "Contains a banned claim."})
    assert resp.status_code == 200, resp.text
    assert resp.json()["submission"]["status"] == "rejected"

    entries = await audit_log.list(organisation_id=org.id, filter={"entity_id": ObjectId(sub_id)}, limit=10)
    assert any(e.action == "submission_rejected" for e in entries)


async def test_reviewer_can_request_changes(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    sub_id = await _create_pending_submission(api_client, headers)
    reviewer_headers = _headers(org.id, reviewer.id)

    resp = await api_client.post(f"/api/submissions/{sub_id}/request-changes", headers=reviewer_headers, json={"comment": "Please fix the price."})
    assert resp.status_code == 200, resp.text
    assert resp.json()["submission"]["status"] == "changes_requested"


# --- Required comments -------------------------------------------------------


async def test_reject_requires_a_non_blank_comment(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    sub_id = await _create_pending_submission(api_client, headers)
    reviewer_headers = _headers(org.id, reviewer.id)

    whitespace_only = await api_client.post(f"/api/submissions/{sub_id}/reject", headers=reviewer_headers, json={"comment": "   "})
    assert whitespace_only.status_code == 422

    no_comment_field = await api_client.post(f"/api/submissions/{sub_id}/reject", headers=reviewer_headers, json={})
    assert no_comment_field.status_code == 422


async def test_request_changes_requires_a_comment(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    sub_id = await _create_pending_submission(api_client, headers)
    reviewer_headers = _headers(org.id, reviewer.id)

    resp = await api_client.post(f"/api/submissions/{sub_id}/request-changes", headers=reviewer_headers, json={})
    assert resp.status_code == 422


async def test_approve_does_not_require_a_comment(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    sub_id = await _create_pending_submission(api_client, headers)
    reviewer_headers = _headers(org.id, reviewer.id)

    resp = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["review"]["comment"] is None


# --- Creator / role enforcement ---------------------------------------------


async def test_creator_cannot_review_own_submission(api_client, demo_headers):
    headers, _org, _creator = demo_headers
    sub_id = await _create_pending_submission(api_client, headers)

    resp = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=headers, json={"comment": "self approve"})
    assert resp.status_code == 403


async def test_a_plain_creator_role_user_cannot_review_anyones_submission(api_client, demo_headers):
    headers, org, _creator = demo_headers
    sub_id = await _create_pending_submission(api_client, headers)
    other_creator = await users.create(
        UserCreate(organisation_id=org.id, name="Other Creator", email="other-creator@example.com", role=UserRole.CREATOR)
    )
    other_headers = _headers(org.id, other_creator.id)

    resp = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=other_headers, json={"comment": "x"})
    assert resp.status_code == 403


async def test_admin_can_review_others_but_not_their_own_submission(api_client, demo_headers):
    headers, org, _creator = demo_headers
    _reviewer, admin = await _reviewer_and_admin(org.id)
    admin_headers = _headers(org.id, admin.id)

    sub_id = await _create_pending_submission(api_client, headers)
    resp = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=admin_headers)
    assert resp.status_code == 200, resp.text

    own_sub = await api_client.post("/api/submissions", headers=admin_headers, json={"title": "Admin's own ad", "content": "x"})
    own_sub_id = own_sub.json()["id"]
    await api_client.post(f"/api/submissions/{own_sub_id}/submit", headers=admin_headers)
    own_resp = await api_client.post(f"/api/submissions/{own_sub_id}/approve", headers=admin_headers)
    assert own_resp.status_code == 403


# --- Cross-organisation access ----------------------------------------------


async def test_cross_org_reviewer_cannot_see_or_decide(api_client, demo_headers):
    headers, _org, _creator = demo_headers
    sub_id = await _create_pending_submission(api_client, headers)

    other_org = await organisations.create(OrganisationCreate(name="Other Org Reviews"))
    other_reviewer = await users.create(
        UserCreate(organisation_id=other_org.id, name="Outside Reviewer", email="outside-reviewer@example.com", role=UserRole.REVIEWER)
    )
    other_headers = _headers(other_org.id, other_reviewer.id)

    assert (await api_client.post(f"/api/submissions/{sub_id}/approve", headers=other_headers)).status_code == 404
    assert (await api_client.get(f"/api/submissions/{sub_id}/reviews", headers=other_headers)).status_code == 404


# --- Invalid submission state -------------------------------------------------


async def test_cannot_review_a_draft(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Draft", "content": "x"})
    sub_id = created.json()["id"]

    resp = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers)
    assert resp.status_code == 409


async def test_cannot_review_an_already_decided_submission_duplicate_decision(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)
    sub_id = await _create_pending_submission(api_client, headers)

    first = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers)
    assert first.status_code == 200

    duplicate = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers)
    assert duplicate.status_code == 409

    conflicting = await api_client.post(f"/api/submissions/{sub_id}/reject", headers=reviewer_headers, json={"comment": "actually no"})
    assert conflicting.status_code == 409  # already-approved submission cannot then be rejected either


# --- Exact revision association / review history / audit --------------------


async def test_review_references_the_exact_current_revision(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)
    sub_id = await _create_pending_submission(api_client, headers)

    content_resp = await api_client.get(f"/api/submissions/{sub_id}/content", headers=headers)
    current_revision_id = content_resp.json()["id"]

    resp = await api_client.post(f"/api/submissions/{sub_id}/request-changes", headers=reviewer_headers, json={"comment": "fix this"})
    assert resp.json()["review"]["revision_id"] == current_revision_id


async def test_review_history_is_preserved_across_multiple_decisions(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)
    sub_id = await _create_pending_submission(api_client, headers)

    await api_client.post(f"/api/submissions/{sub_id}/request-changes", headers=reviewer_headers, json={"comment": "fix the price"})
    await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "Updated ad copy."})
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers, json={"comment": "Good now."})

    history = await api_client.get(f"/api/submissions/{sub_id}/reviews", headers=headers)
    assert history.status_code == 200
    decisions = [r["decision"] for r in history.json()]
    # BOTH decisions preserved, in order -- history is never overwritten,
    # even though the submission's own status moved on twice since.
    assert decisions == ["changes_requested", "approved"]


# --- Concurrency -------------------------------------------------------------


async def test_concurrent_approve_and_reject_only_one_wins(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, admin = await _reviewer_and_admin(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)
    admin_headers = _headers(org.id, admin.id)
    sub_id = await _create_pending_submission(api_client, headers)

    approve_call = api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers)
    reject_call = api_client.post(f"/api/submissions/{sub_id}/reject", headers=admin_headers, json={"comment": "conflicting"})
    approve_resp, reject_resp = await asyncio.gather(approve_call, reject_call)

    assert {approve_resp.status_code, reject_resp.status_code} == {200, 409}

    final = await api_client.get(f"/api/submissions/{sub_id}", headers=headers)
    assert final.json()["status"] in ("approved", "rejected")

    # Exactly one Review record exists -- the losing request's atomic claim
    # never matched, so it never created a Review or audit_log entry either.
    history = await api_client.get(f"/api/submissions/{sub_id}/reviews", headers=headers)
    assert len(history.json()) == 1


# --- Creator edits after request-changes + resubmission ----------------------


async def test_creator_can_edit_and_resubmit_after_changes_requested_then_get_approved(api_client, demo_headers):
    headers, org, _creator = demo_headers
    reviewer, _admin = await _reviewer_and_admin(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)
    sub_id = await _create_pending_submission(api_client, headers, content="Original copy with a mistake.")

    rc_resp = await api_client.post(f"/api/submissions/{sub_id}/request-changes", headers=reviewer_headers, json={"comment": "Fix the mistake."})
    assert rc_resp.json()["submission"]["status"] == "changes_requested"

    # Existing Phase 4 lifecycle, unchanged: editing a changes_requested
    # submission creates a new revision and returns it to draft.
    revise_resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "Corrected copy."})
    assert revise_resp.status_code == 201
    assert revise_resp.json()["submission"]["status"] == "draft"
    assert revise_resp.json()["revision"]["version"] == 2
    new_revision_id = revise_resp.json()["revision"]["id"]

    submit_resp = await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    assert submit_resp.json()["status"] == "pending_review"

    approve_resp = await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers, json={"comment": "Now correct."})
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["submission"]["status"] == "approved"
    # Decided against the NEW revision, never the stale one the first
    # (changes_requested) decision was made against.
    assert approve_resp.json()["review"]["revision_id"] == new_revision_id

    history = await api_client.get(f"/api/submissions/{sub_id}/reviews", headers=headers)
    assert [r["decision"] for r in history.json()] == ["changes_requested", "approved"]
