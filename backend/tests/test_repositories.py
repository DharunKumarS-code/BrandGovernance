from datetime import datetime, timezone

import pytest

from app.models import (
    BrandFactCreate,
    FindingCategory,
    FindingCreate,
    FindingSeverity,
    FindingSource,
    OrganisationCreate,
    RevisionCreate,
    SubmissionCreate,
    SubmissionStatus,
    UserCreate,
    UserRole,
    Verdict,
)
from app.repositories import brand_facts, findings, organisations, revisions, submissions, users


async def _make_org():
    return await organisations.create(OrganisationCreate(name="Test Org"))


async def test_organisation_create_read_update_list():
    org = await organisations.create(OrganisationCreate(name="Acme"))
    assert org.name == "Acme"
    assert org.created_at == org.updated_at

    fetched = await organisations.get(org.id)
    assert fetched is not None
    assert fetched.name == "Acme"

    updated = await organisations.update(org.id, {"name": "Acme Inc"})
    assert updated.name == "Acme Inc"
    assert updated.updated_at >= org.updated_at

    all_orgs = await organisations.list()
    assert any(o.id == org.id for o in all_orgs)


async def test_user_crud_is_scoped_to_organisation():
    org_a = await _make_org()
    org_b = await _make_org()

    user_a = await users.create(
        UserCreate(organisation_id=org_a.id, name="Alice", email="alice@example.com", role=UserRole.ADMIN)
    )
    await users.create(
        UserCreate(organisation_id=org_b.id, name="Bob", email="bob@example.com", role=UserRole.CREATOR)
    )

    # Cross-org read is blocked even with the correct id.
    assert await users.get(user_a.id, organisation_id=org_b.id) is None
    assert await users.get(user_a.id, organisation_id=org_a.id) is not None

    org_a_users = await users.list(organisation_id=org_a.id)
    assert len(org_a_users) == 1
    assert org_a_users[0].name == "Alice"


async def test_user_update_and_delete():
    org = await _make_org()
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Carl", email="carl@example.com", role=UserRole.REVIEWER)
    )

    updated = await users.update(user.id, {"role": UserRole.ADMIN}, organisation_id=org.id)
    assert updated.role == UserRole.ADMIN

    deleted = await users.delete(user.id, organisation_id=org.id)
    assert deleted is True
    assert await users.get(user.id, organisation_id=org.id) is None


async def test_brand_fact_outdated_vs_current():
    org = await _make_org()
    doc_id = org.id  # any ObjectId works as a stand-in reference for this test

    old_fact = await brand_facts.create(
        BrandFactCreate(
            organisation_id=org.id,
            subject="Nova Buds Pro",
            attribute="price",
            value="129",
            unit="USD",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
            valid_to=datetime(2025, 6, 1, tzinfo=timezone.utc),
            source_doc_id=doc_id,
            page=5,
            quote="launches at $129",
        )
    )
    current_fact = await brand_facts.create(
        BrandFactCreate(
            organisation_id=org.id,
            subject="Nova Buds Pro",
            attribute="price",
            value="149",
            unit="USD",
            valid_from=datetime(2025, 6, 1, tzinfo=timezone.utc),
            valid_to=None,
            source_doc_id=doc_id,
            page=5,
            quote="now priced at $149",
        )
    )

    facts = await brand_facts.list(
        organisation_id=org.id, filter={"subject": "Nova Buds Pro", "attribute": "price"}
    )
    assert len(facts) == 2
    assert old_fact.valid_to is not None
    assert current_fact.valid_to is None


async def test_submission_revision_finding_chain():
    org = await _make_org()
    creator = await users.create(
        UserCreate(organisation_id=org.id, name="Dana", email="dana@example.com", role=UserRole.CREATOR)
    )

    submission = await submissions.create(
        SubmissionCreate(
            organisation_id=org.id,
            title="Launch ad",
            creator_id=creator.id,
            current_revision=1,
            status=SubmissionStatus.DRAFT,
        )
    )
    revision = await revisions.create(
        RevisionCreate(
            organisation_id=org.id,
            submission_id=submission.id,
            version=1,
            content="Nova Buds Pro deliver 12 hours of playback.",
            content_type="text/plain",
            author_id=creator.id,
        )
    )

    finding = await findings.create(
        FindingCreate(
            organisation_id=org.id,
            revision_id=revision.id,
            category=FindingCategory.FACT,
            severity=FindingSeverity.HIGH,
            span_text="12 hours of playback",
            explanation="Battery life is documented as 8 hours, not 12.",
            verdict=Verdict.CONTRADICTED,
            evidence_record_type="brand_facts",
            evidence_record_id=submission.id,
            evidence_quote="up to 8 hours of playback",
            suggestion="8 hours of playback",
            source=FindingSource.RULE,
        )
    )

    assert finding.status.value == "open"
    found = await findings.list(organisation_id=org.id, filter={"revision_id": revision.id})
    assert len(found) == 1
    assert found[0].verdict == Verdict.CONTRADICTED


def test_unsupported_verdict_is_distinct_from_contradicted():
    assert Verdict.UNSUPPORTED != Verdict.CONTRADICTED
    assert {v.value for v in Verdict} == {
        "contradicted",
        "outdated",
        "unsupported",
        "verified",
        "needs_review",
    }
