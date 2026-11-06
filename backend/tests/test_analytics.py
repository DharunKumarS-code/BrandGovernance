"""Phase 8 Stage 1: analytics endpoint -- focused tests."""

from bson import ObjectId

from app.models import (
    FindingCategory,
    FindingCreate,
    FindingSeverity,
    FindingSource,
    GuidelineChunkCreate,
    GuidelineDocCreate,
    GuidelineDocStatus,
    OrganisationCreate,
    TerminologyCreate,
    UserCreate,
    UserRole,
    Verdict,
)
from app.repositories import findings, guideline_chunks, guideline_docs, organisations, terminology, users


async def _org():
    org = await organisations.create(OrganisationCreate(name="Analytics Test Org"))
    user = await users.create(UserCreate(organisation_id=org.id, name="Tester", email="analytics-test@example.com", role=UserRole.ADMIN))
    return org, user


async def _finding(org_id, **overrides):
    defaults = dict(
        organisation_id=org_id, revision_id=ObjectId(),
        category=FindingCategory.CLAIM, severity=FindingSeverity.MEDIUM, span_text="x", explanation="x",
        verdict=Verdict.CONTRADICTED, source=FindingSource.RULE,
    )
    defaults.update(overrides)
    return await findings.create(FindingCreate(**defaults))


async def test_analytics_empty_org_returns_zeroed_response(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.get("/api/analytics/summary", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["findings_by_category"] == []
    assert body["top_terminology_violations"] == []
    assert body["top_claim_policy_violations"] == []
    assert body["insufficient_evidence_count"] == 0
    assert body["unembedded_guideline_chunks"] == 0


async def test_findings_by_category_and_severity(api_client, demo_headers):
    headers, org, _user = demo_headers
    await _finding(org.id, category=FindingCategory.TERMINOLOGY, severity=FindingSeverity.HIGH)
    await _finding(org.id, category=FindingCategory.TERMINOLOGY, severity=FindingSeverity.HIGH)
    await _finding(org.id, category=FindingCategory.CLAIM, severity=FindingSeverity.LOW)

    resp = await api_client.get("/api/analytics/summary", headers=headers)
    rows = {(r["category"], r["severity"]): r["count"] for r in resp.json()["findings_by_category"]}
    assert rows[("terminology", "high")] == 2
    assert rows[("claim", "low")] == 1


async def test_top_terminology_violations_named_and_counted(api_client, demo_headers):
    headers, org, _user = demo_headers
    term = await terminology.create(TerminologyCreate(organisation_id=org.id, preferred_term="Approved Term", banned_variants=["bad term"], reason="x"))
    await _finding(org.id, category=FindingCategory.TERMINOLOGY, evidence_record_type="terminology", evidence_record_id=term.id)
    await _finding(org.id, category=FindingCategory.TERMINOLOGY, evidence_record_type="terminology", evidence_record_id=term.id)

    resp = await api_client.get("/api/analytics/summary", headers=headers)
    top = resp.json()["top_terminology_violations"]
    assert len(top) == 1
    assert top[0]["preferred_term"] == "Approved Term"
    assert top[0]["count"] == 2


async def test_insufficient_evidence_and_unembedded_chunks_counted(api_client, demo_headers):
    headers, org, user = demo_headers
    f = await _finding(org.id)
    await findings.update(f.id, {"evidence": {"status": "insufficient", "reason": "x", "unavailable": True, "quote_verified": False}}, organisation_id=org.id)

    doc = await guideline_docs.create(GuidelineDocCreate(organisation_id=org.id, title="Doc", filename="d.pdf", uploaded_by=user.id, page_count=1, status=GuidelineDocStatus.READY))
    await guideline_chunks.create(GuidelineChunkCreate(organisation_id=org.id, doc_id=doc.id, page=1, chunk_index=0, text="x", embedding=None))

    resp = await api_client.get("/api/analytics/summary", headers=headers)
    body = resp.json()
    assert body["insufficient_evidence_count"] == 1
    assert body["unembedded_guideline_chunks"] == 1


async def test_analytics_organisation_isolation(api_client, demo_headers):
    headers, org_a, _user = demo_headers
    await _finding(org_a.id, category=FindingCategory.TERMINOLOGY, severity=FindingSeverity.HIGH)

    org_b, user_b = await _org()
    headers_b = {"X-Organisation-Id": str(org_b.id), "X-User-Id": str(user_b.id)}

    resp_b = await api_client.get("/api/analytics/summary", headers=headers_b)
    assert resp_b.json()["findings_by_category"] == []  # org A's findings must not leak into org B
