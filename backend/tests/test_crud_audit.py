"""Phase 2 audit: direct create/get/list/update/delete coverage for every
collection that the generic repository and seed-script tests don't already
exercise end-to-end (reviews, audit_log, guideline_docs, guideline_chunks,
terminology, claim_policies, assets)."""

from app.models import (
    AssetCreate,
    AssetStatus,
    AssetType,
    AuditLogCreate,
    ClaimPolicyCreate,
    ClaimPolicyStatus,
    GuidelineChunkCreate,
    GuidelineDocCreate,
    GuidelineDocStatus,
    OrganisationCreate,
    ReviewCreate,
    ReviewDecision,
    TerminologyCreate,
    UserCreate,
    UserRole,
)
from app.repositories import (
    assets,
    audit_log,
    claim_policies,
    guideline_chunks,
    guideline_docs,
    organisations,
    reviews,
    terminology,
    users,
)


async def _make_org_and_user():
    org = await organisations.create(OrganisationCreate(name="CRUD Audit Org"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Audit User", email="audit@example.com", role=UserRole.ADMIN)
    )
    return org, user


async def test_guideline_doc_full_crud():
    org, user = await _make_org_and_user()
    doc = await guideline_docs.create(
        GuidelineDocCreate(
            organisation_id=org.id, title="Guide", filename="g.pdf", uploaded_by=user.id,
            page_count=10, status=GuidelineDocStatus.PENDING,
        )
    )
    assert (await guideline_docs.get(doc.id, organisation_id=org.id)) is not None
    assert len(await guideline_docs.list(organisation_id=org.id)) == 1

    updated = await guideline_docs.update(doc.id, {"status": GuidelineDocStatus.READY}, organisation_id=org.id)
    assert updated.status == GuidelineDocStatus.READY

    assert await guideline_docs.delete(doc.id, organisation_id=org.id) is True
    assert (await guideline_docs.get(doc.id, organisation_id=org.id)) is None


async def test_guideline_chunk_full_crud():
    org, user = await _make_org_and_user()
    doc = await guideline_docs.create(
        GuidelineDocCreate(
            organisation_id=org.id, title="Guide", filename="g.pdf", uploaded_by=user.id,
            page_count=10, status=GuidelineDocStatus.READY,
        )
    )
    chunk = await guideline_chunks.create(
        GuidelineChunkCreate(organisation_id=org.id, doc_id=doc.id, page=1, chunk_index=0, text="hello world")
    )
    assert (await guideline_chunks.get(chunk.id, organisation_id=org.id)) is not None
    assert len(await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": doc.id})) == 1

    updated = await guideline_chunks.update(chunk.id, {"text": "updated text"}, organisation_id=org.id)
    assert updated.text == "updated text"

    assert await guideline_chunks.delete(chunk.id, organisation_id=org.id) is True
    assert (await guideline_chunks.get(chunk.id, organisation_id=org.id)) is None


async def test_terminology_full_crud():
    org, _ = await _make_org_and_user()
    term = await terminology.create(
        TerminologyCreate(organisation_id=org.id, preferred_term="X", banned_variants=["x"], reason="r")
    )
    assert (await terminology.get(term.id, organisation_id=org.id)) is not None
    assert len(await terminology.list(organisation_id=org.id)) == 1

    updated = await terminology.update(term.id, {"reason": "updated reason"}, organisation_id=org.id)
    assert updated.reason == "updated reason"

    assert await terminology.delete(term.id, organisation_id=org.id) is True
    assert (await terminology.get(term.id, organisation_id=org.id)) is None


async def test_claim_policy_full_crud():
    org, _ = await _make_org_and_user()
    policy = await claim_policies.create(
        ClaimPolicyCreate(organisation_id=org.id, pattern="best", status=ClaimPolicyStatus.NEEDS_EVIDENCE)
    )
    assert (await claim_policies.get(policy.id, organisation_id=org.id)) is not None
    assert len(await claim_policies.list(organisation_id=org.id)) == 1

    updated = await claim_policies.update(policy.id, {"status": ClaimPolicyStatus.BANNED}, organisation_id=org.id)
    assert updated.status == ClaimPolicyStatus.BANNED

    assert await claim_policies.delete(policy.id, organisation_id=org.id) is True
    assert (await claim_policies.get(policy.id, organisation_id=org.id)) is None


async def test_asset_full_crud():
    org, _ = await _make_org_and_user()
    asset = await assets.create(
        AssetCreate(organisation_id=org.id, type=AssetType.COLOUR, name="Test Blue", status=AssetStatus.APPROVED, hex_value="#000000")
    )
    assert (await assets.get(asset.id, organisation_id=org.id)) is not None
    assert len(await assets.list(organisation_id=org.id)) == 1

    updated = await assets.update(asset.id, {"status": AssetStatus.DEPRECATED}, organisation_id=org.id)
    assert updated.status == AssetStatus.DEPRECATED

    assert await assets.delete(asset.id, organisation_id=org.id) is True
    assert (await assets.get(asset.id, organisation_id=org.id)) is None


async def test_review_full_crud():
    org, user = await _make_org_and_user()
    # minimal stand-in ids; review model only constrains type, not referential integrity in Phase 2
    review = await reviews.create(
        ReviewCreate(
            organisation_id=org.id,
            submission_id=user.id,
            revision_id=user.id,
            reviewer_id=user.id,
            decision=ReviewDecision.CHANGES_REQUESTED,
            comment="needs work",
        )
    )
    assert (await reviews.get(review.id, organisation_id=org.id)) is not None
    assert len(await reviews.list(organisation_id=org.id)) == 1

    updated = await reviews.update(review.id, {"decision": ReviewDecision.APPROVED}, organisation_id=org.id)
    assert updated.decision == ReviewDecision.APPROVED

    assert await reviews.delete(review.id, organisation_id=org.id) is True
    assert (await reviews.get(review.id, organisation_id=org.id)) is None


async def test_audit_log_full_crud():
    org, user = await _make_org_and_user()
    entry = await audit_log.create(
        AuditLogCreate(
            organisation_id=org.id, actor_id=user.id, action="created_submission",
            entity_type="submission", entity_id=user.id, details={"note": "test"},
        )
    )
    assert (await audit_log.get(entry.id, organisation_id=org.id)) is not None
    assert len(await audit_log.list(organisation_id=org.id)) == 1

    updated = await audit_log.update(entry.id, {"action": "updated_submission"}, organisation_id=org.id)
    assert updated.action == "updated_submission"

    assert await audit_log.delete(entry.id, organisation_id=org.id) is True
    assert (await audit_log.get(entry.id, organisation_id=org.id)) is None
