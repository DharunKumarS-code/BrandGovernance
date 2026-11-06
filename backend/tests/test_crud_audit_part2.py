"""Phase 2 audit, part 2: closes get/update/delete coverage gaps for
brand_facts, submissions, revisions and findings -- previously only
create/list were exercised for these four collections."""

from datetime import datetime, timezone

from app.models import (
    BrandFactCreate,
    FindingCategory,
    FindingCreate,
    FindingSeverity,
    FindingSource,
    FindingStatus,
    OrganisationCreate,
    RevisionCreate,
    SubmissionCreate,
    SubmissionStatus,
    UserCreate,
    UserRole,
    Verdict,
)
from app.repositories import brand_facts, findings, organisations, revisions, submissions, users


async def _make_org_and_user():
    org = await organisations.create(OrganisationCreate(name="CRUD Audit Org 2"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Audit User 2", email="audit2@example.com", role=UserRole.CREATOR)
    )
    return org, user


async def test_brand_fact_get_update_delete():
    org, _ = await _make_org_and_user()
    fact = await brand_facts.create(
        BrandFactCreate(
            organisation_id=org.id, subject="Widget", attribute="price", value="10", unit="USD",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc), valid_to=None,
            source_doc_id=org.id, page=1, quote="10 dollars",
        )
    )
    assert (await brand_facts.get(fact.id, organisation_id=org.id)) is not None

    updated = await brand_facts.update(fact.id, {"value": "12"}, organisation_id=org.id)
    assert updated.value == "12"

    assert await brand_facts.delete(fact.id, organisation_id=org.id) is True
    assert (await brand_facts.get(fact.id, organisation_id=org.id)) is None


async def test_submission_get_update_delete():
    org, user = await _make_org_and_user()
    submission = await submissions.create(
        SubmissionCreate(organisation_id=org.id, title="Ad", creator_id=user.id, status=SubmissionStatus.DRAFT)
    )
    assert (await submissions.get(submission.id, organisation_id=org.id)) is not None

    updated = await submissions.update(
        submission.id, {"status": SubmissionStatus.PENDING_REVIEW}, organisation_id=org.id
    )
    assert updated.status == SubmissionStatus.PENDING_REVIEW

    assert await submissions.delete(submission.id, organisation_id=org.id) is True
    assert (await submissions.get(submission.id, organisation_id=org.id)) is None


async def test_revision_get_update_delete():
    org, user = await _make_org_and_user()
    submission = await submissions.create(
        SubmissionCreate(organisation_id=org.id, title="Ad", creator_id=user.id, status=SubmissionStatus.DRAFT)
    )
    revision = await revisions.create(
        RevisionCreate(
            organisation_id=org.id, submission_id=submission.id, version=1,
            content="draft copy", content_type="text/plain", author_id=user.id,
        )
    )
    assert (await revisions.get(revision.id, organisation_id=org.id)) is not None

    updated = await revisions.update(revision.id, {"content": "revised copy"}, organisation_id=org.id)
    assert updated.content == "revised copy"

    assert await revisions.delete(revision.id, organisation_id=org.id) is True
    assert (await revisions.get(revision.id, organisation_id=org.id)) is None


async def test_finding_get_update_delete():
    org, user = await _make_org_and_user()
    submission = await submissions.create(
        SubmissionCreate(organisation_id=org.id, title="Ad", creator_id=user.id, status=SubmissionStatus.DRAFT)
    )
    revision = await revisions.create(
        RevisionCreate(
            organisation_id=org.id, submission_id=submission.id, version=1,
            content="draft copy", content_type="text/plain", author_id=user.id,
        )
    )
    finding = await findings.create(
        FindingCreate(
            organisation_id=org.id, revision_id=revision.id, category=FindingCategory.CLAIM,
            severity=FindingSeverity.MEDIUM, span_text="x", explanation="x", verdict=Verdict.NEEDS_REVIEW,
            evidence_record_type="brand_facts", evidence_record_id=org.id, evidence_quote="x",
            source=FindingSource.LLM,
        )
    )
    assert (await findings.get(finding.id, organisation_id=org.id)) is not None

    updated = await findings.update(finding.id, {"status": FindingStatus.ACCEPTED}, organisation_id=org.id)
    assert updated.status == FindingStatus.ACCEPTED

    assert await findings.delete(finding.id, organisation_id=org.id) is True
    assert (await findings.get(finding.id, organisation_id=org.id)) is None
