"""Phase 7 Stage 2 tests: the real, database-driven dashboard summary.

Uses direct repository calls to set up precise revision/finding/review
scenarios (exact analyzed_at timestamps, exact statuses) alongside the real
HTTP API for submission lifecycle actions where that's simpler. No real
Gemini calls anywhere in this file.
"""

from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.models import (
    AuditLogCreate,
    FindingCategory,
    FindingCreate,
    FindingSeverity,
    FindingStatus,
    OrganisationCreate,
    RevisionCreate,
    SubmissionCreate,
    SubmissionStatus,
    UserCreate,
    UserRole,
    Verdict,
)
from app.repositories import audit_log, findings, organisations, revisions, submissions, users


def _headers(org_id, user_id):
    return {"X-Organisation-Id": str(org_id), "X-User-Id": str(user_id)}


async def _reviewer(org_id):
    return await users.create(
        UserCreate(organisation_id=org_id, name="Reviewer", email="dash-reviewer@example.com", role=UserRole.REVIEWER)
    )


async def _submission(org_id, creator_id, status=SubmissionStatus.DRAFT, current_revision=1, title="Ad"):
    return await submissions.create(
        SubmissionCreate(organisation_id=org_id, title=title, creator_id=creator_id, current_revision=current_revision, status=status)
    )


async def _revision(org_id, submission_id, author_id, version=1, analyzed_at=None, content="content"):
    rev = await revisions.create(
        RevisionCreate(organisation_id=org_id, submission_id=submission_id, version=version, content=content, content_type="text/plain", author_id=author_id)
    )
    if analyzed_at is not None:
        rev = await revisions.update(rev.id, {"analyzed_at": analyzed_at}, organisation_id=org_id)
    return rev


async def _finding(org_id, revision_id, severity=FindingSeverity.MEDIUM, status=FindingStatus.OPEN, verdict=Verdict.CONTRADICTED):
    return await findings.create(
        FindingCreate(
            organisation_id=org_id, revision_id=revision_id, category=FindingCategory.CLAIM, severity=severity,
            span_text="x", explanation="x", verdict=verdict, source="rule", status=status,
        )
    )


# --- A. Status counts --------------------------------------------------------


async def test_status_counts_match_and_sum_to_total(api_client, demo_headers):
    headers, org, creator = demo_headers
    reviewer = await _reviewer(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)

    # draft
    await api_client.post("/api/submissions", headers=headers, json={"title": "Draft one", "content": "x"})
    # pending_review
    pending = await api_client.post("/api/submissions", headers=headers, json={"title": "Pending one", "content": "x"})
    await api_client.post(f"/api/submissions/{pending.json()['id']}/submit", headers=headers)
    # changes_requested
    cr = await api_client.post("/api/submissions", headers=headers, json={"title": "CR one", "content": "x"})
    cr_id = cr.json()["id"]
    await api_client.post(f"/api/submissions/{cr_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{cr_id}/request-changes", headers=reviewer_headers, json={"comment": "fix"})
    # approved
    appr = await api_client.post("/api/submissions", headers=headers, json={"title": "Appr one", "content": "x"})
    appr_id = appr.json()["id"]
    await api_client.post(f"/api/submissions/{appr_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{appr_id}/approve", headers=reviewer_headers)
    # rejected
    rej = await api_client.post("/api/submissions", headers=headers, json={"title": "Rej one", "content": "x"})
    rej_id = rej.json()["id"]
    await api_client.post(f"/api/submissions/{rej_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{rej_id}/reject", headers=reviewer_headers, json={"comment": "no"})

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    s = resp.json()["submissions"]
    assert s["draft"] == 1
    assert s["pending_review"] == 1
    assert s["changes_requested"] == 1
    assert s["approved"] == 1
    assert s["rejected"] == 1
    assert s["total"] == 5
    assert s["draft"] + s["pending_review"] + s["changes_requested"] + s["approved"] + s["rejected"] == s["total"]


# --- B. Submissions with AI findings (latest ANALYSED revision only) --------


async def test_latest_analysed_revision_used_not_latest_overall(api_client, demo_headers):
    headers, org, creator = demo_headers
    sub = await _submission(org.id, creator.id, status=SubmissionStatus.PENDING_REVIEW, current_revision=2)
    v1 = await _revision(org.id, sub.id, creator.id, version=1, analyzed_at=datetime.now(timezone.utc))
    await _finding(org.id, v1.id)  # open finding on the only analysed revision
    # v2 exists (is the submission's CURRENT revision) but was never analysed.
    await _revision(org.id, sub.id, creator.id, version=2, analyzed_at=None)

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    body = resp.json()
    assert body["submissions"]["with_ai_findings"] == 1
    assert body["issues"]["open_total"] == 1


async def test_older_analysed_revision_findings_ignored_when_newer_analysed(api_client, demo_headers):
    headers, org, creator = demo_headers
    sub = await _submission(org.id, creator.id, status=SubmissionStatus.PENDING_REVIEW, current_revision=2)
    now = datetime.now(timezone.utc)
    v1 = await _revision(org.id, sub.id, creator.id, version=1, analyzed_at=now - timedelta(hours=1))
    await _finding(org.id, v1.id)  # stale open finding on the OLDER analysed revision
    v2 = await _revision(org.id, sub.id, creator.id, version=2, analyzed_at=now)  # newer, re-analysed, clean (no findings)

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    body = resp.json()
    # v2 (higher version) is latest-analysed and has zero findings -> v1's
    # stale finding must NOT be counted.
    assert body["submissions"]["with_ai_findings"] == 0
    assert body["issues"]["open_total"] == 0


async def test_dismissed_findings_excluded_and_no_duplicate_submission_count(api_client, demo_headers):
    headers, org, creator = demo_headers
    sub = await _submission(org.id, creator.id, status=SubmissionStatus.PENDING_REVIEW)
    v1 = await _revision(org.id, sub.id, creator.id, version=1, analyzed_at=datetime.now(timezone.utc))
    await _finding(org.id, v1.id, status=FindingStatus.OPEN)
    await _finding(org.id, v1.id, status=FindingStatus.OPEN)
    await _finding(org.id, v1.id, status=FindingStatus.DISMISSED)

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    body = resp.json()
    assert body["submissions"]["with_ai_findings"] == 1  # ONE submission, not one per finding
    assert body["issues"]["open_total"] == 2  # dismissed one excluded


async def test_submission_without_analysed_revision_excluded(api_client, demo_headers):
    headers, org, creator = demo_headers
    sub = await _submission(org.id, creator.id, status=SubmissionStatus.DRAFT)
    await _revision(org.id, sub.id, creator.id, version=1, analyzed_at=None)

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    body = resp.json()
    assert body["submissions"]["with_ai_findings"] == 0
    assert body["issues"]["open_total"] == 0


# --- C. Open issues + severity breakdown -------------------------------------


async def test_severity_breakdown_is_correct(api_client, demo_headers):
    headers, org, creator = demo_headers
    sub = await _submission(org.id, creator.id, status=SubmissionStatus.PENDING_REVIEW)
    v1 = await _revision(org.id, sub.id, creator.id, version=1, analyzed_at=datetime.now(timezone.utc))
    await _finding(org.id, v1.id, severity=FindingSeverity.HIGH)
    await _finding(org.id, v1.id, severity=FindingSeverity.HIGH)
    await _finding(org.id, v1.id, severity=FindingSeverity.MEDIUM)
    await _finding(org.id, v1.id, severity=FindingSeverity.LOW)
    await _finding(org.id, v1.id, severity=FindingSeverity.LOW, status=FindingStatus.DISMISSED)  # excluded

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    by_sev = resp.json()["issues"]["by_severity"]
    assert by_sev == {"high": 2, "medium": 1, "low": 1}
    assert resp.json()["issues"]["open_total"] == 4


# --- D. Review statistics ----------------------------------------------------


async def test_completed_reviews_counts_records_not_unique_submissions(api_client, demo_headers):
    headers, org, creator = demo_headers
    reviewer = await _reviewer(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)

    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Round trip", "content": "v1"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{sub_id}/request-changes", headers=reviewer_headers, json={"comment": "fix"})
    await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2"})
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers, json={"comment": "good"})

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    reviews_stats = resp.json()["reviews"]
    # TWO decisions were made on this ONE submission -- completed must be 2.
    assert reviews_stats["completed"] == 2
    assert reviews_stats["currently_approved"] == 1  # but only 1 submission is CURRENTLY approved
    assert reviews_stats["pending"] == 0


async def test_pending_and_currently_approved_rejected_counts(api_client, demo_headers):
    headers, org, creator = demo_headers
    reviewer = await _reviewer(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)

    pending = await api_client.post("/api/submissions", headers=headers, json={"title": "P", "content": "x"})
    await api_client.post(f"/api/submissions/{pending.json()['id']}/submit", headers=headers)

    rej = await api_client.post("/api/submissions", headers=headers, json={"title": "R", "content": "x"})
    rej_id = rej.json()["id"]
    await api_client.post(f"/api/submissions/{rej_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{rej_id}/reject", headers=reviewer_headers, json={"comment": "no"})

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    reviews_stats = resp.json()["reviews"]
    assert reviews_stats["pending"] == 1
    assert reviews_stats["currently_rejected"] == 1
    assert reviews_stats["currently_approved"] == 0


# --- E. Recent activity ------------------------------------------------------


async def test_recent_activity_newest_first_and_capped_at_15(api_client, demo_headers):
    headers, org, creator = demo_headers
    sub_ids = []
    for i in range(18):
        created = await api_client.post("/api/submissions", headers=headers, json={"title": f"Ad {i}", "content": "x"})
        sub_ids.append(created.json()["id"])

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    activity = resp.json()["recent_activity"]
    assert len(activity) == 15
    timestamps = [a["created_at"] for a in activity]
    assert timestamps == sorted(timestamps, reverse=True)  # newest first
    # The newest entry must be the LAST submission created (Ad 17).
    assert activity[0]["submission_title"] == "Ad 17"


async def test_recent_activity_resolves_actor_and_submission(api_client, demo_headers):
    headers, org, creator = demo_headers
    reviewer = await _reviewer(org.id)
    reviewer_headers = _headers(org.id, reviewer.id)

    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Traceable Ad", "content": "x"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    await api_client.post(f"/api/submissions/{sub_id}/approve", headers=reviewer_headers, json={"comment": "ok"})

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    activity = resp.json()["recent_activity"]
    approved_entry = next(a for a in activity if a["action"] == "submission_approved")
    assert approved_entry["actor_name"] == "Reviewer"
    assert approved_entry["submission_title"] == "Traceable Ad"
    assert approved_entry["submission_id"] == sub_id

    created_entry = next(a for a in activity if a["action"] == "submission_created")
    assert created_entry["submission_title"] == "Traceable Ad"


async def test_recent_activity_handles_missing_actor_gracefully(api_client, demo_headers):
    headers, org, creator = demo_headers
    ghost_actor_id = ObjectId()  # never a real user
    # entity_type "finding" with no "submission_id" in details -- a real
    # shape (e.g. a very old finding-level event), but with no submission
    # reference recoverable at all.
    await audit_log.create(
        AuditLogCreate(
            organisation_id=org.id, actor_id=ghost_actor_id, action="finding_dismissed", entity_type="finding",
            entity_id=ObjectId(), details={},
        )
    )

    resp = await api_client.get("/api/dashboard/summary", headers=headers)
    assert resp.status_code == 200
    activity = resp.json()["recent_activity"]
    ghost_entry = next(a for a in activity if a["action"] == "finding_dismissed")
    assert ghost_entry["actor_name"] is None  # unknown actor -- degraded gracefully, nothing fabricated
    assert ghost_entry["submission_id"] is None
    assert ghost_entry["submission_title"] is None


# --- Organisation isolation ---------------------------------------------------


async def test_dashboard_organisation_isolation(api_client, demo_headers):
    headers, org_a, creator_a = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Org A Ad", "content": "x"})
    await api_client.post(f"/api/submissions/{created.json()['id']}/submit", headers=headers)

    org_b = await organisations.create(OrganisationCreate(name="Dashboard Isolation Org B"))
    user_b = await users.create(UserCreate(organisation_id=org_b.id, name="B User", email="dash-b@example.com", role=UserRole.ADMIN))
    headers_b = _headers(org_b.id, user_b.id)

    resp_b = await api_client.get("/api/dashboard/summary", headers=headers_b)
    body_b = resp_b.json()
    assert body_b["submissions"]["total"] == 0
    assert body_b["recent_activity"] == []
