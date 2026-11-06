"""Phase 6, Module 1 tests: app/services/evidence.py.

Builds real Finding documents (via the findings repository, same as every
other test in this suite) against real brand_fact/terminology/
claim_policy/guideline_chunk/guideline_doc records, then checks that
validate_finding_evidence() classifies each case correctly and never
invents a quote, page number, or evidence record.
"""

from datetime import datetime, timezone

from bson import ObjectId

from app.models import (
    BrandFactCreate,
    ClaimPolicyCreate,
    ClaimPolicyStatus,
    EvidenceStatus,
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
from app.repositories import (
    brand_facts,
    claim_policies,
    findings,
    guideline_chunks,
    guideline_docs,
    organisations,
    terminology,
    users,
)
from app.services.evidence import validate_finding_evidence

DUMMY_REVISION_ID = ObjectId()


async def _org():
    org = await organisations.create(OrganisationCreate(name="Evidence Test Org"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Tester", email="evidence-test@example.com", role=UserRole.ADMIN)
    )
    return org, user


async def _make_finding(org_id, **overrides):
    defaults = dict(
        organisation_id=org_id,
        revision_id=DUMMY_REVISION_ID,
        category=FindingCategory.FACT,
        severity=FindingSeverity.MEDIUM,
        span_text="some span",
        explanation="some explanation",
        verdict=Verdict.VERIFIED,
        source=FindingSource.RULE,
    )
    defaults.update(overrides)
    return await findings.create(FindingCreate(**defaults))


# --- Brand fact (FACT category) evidence ---------------------------------


async def test_verified_fact_with_matching_quote_is_supported():
    org, _user = await _org()
    doc = await guideline_docs.create(
        GuidelineDocCreate(organisation_id=org.id, title="Nova Guide", filename="g.pdf", uploaded_by=_user.id, page_count=10, status=GuidelineDocStatus.READY)
    )
    fact = await brand_facts.create(
        BrandFactCreate(
            organisation_id=org.id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc), source_doc_id=doc.id, page=4,
            quote="Nova Buds Pro deliver up to 8 hours of playback.",
        )
    )
    finding = await _make_finding(
        org.id, verdict=Verdict.VERIFIED, evidence_record_type="brand_fact", evidence_record_id=fact.id,
        evidence_quote="Nova Buds Pro deliver up to 8 hours of playback.", evidence_subject="Nova Buds Pro", evidence_attribute="battery_life",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)

    assert evidence.status == EvidenceStatus.SUPPORTED
    assert evidence.quote_verified is True
    assert evidence.unavailable is False
    assert evidence.source_type == "brand_fact"
    assert evidence.source_id == fact.id
    assert evidence.guideline_doc_id == doc.id
    assert evidence.guideline_doc_title == "Nova Guide"
    assert evidence.page == 4  # the real PDF page stored on the fact, never a chunk index


async def test_outdated_fact_is_supported():
    org, _user = await _org()
    fact = await brand_facts.create(
        BrandFactCreate(
            organisation_id=org.id, subject="Nova Buds Pro", attribute="price", value="129", unit="USD",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc), valid_to=datetime(2025, 6, 1, tzinfo=timezone.utc),
            quote="Intro price $129.",
        )
    )
    finding = await _make_finding(
        org.id, verdict=Verdict.OUTDATED, evidence_record_type="brand_fact", evidence_record_id=fact.id,
        evidence_quote="Intro price $129.", evidence_subject="Nova Buds Pro", evidence_attribute="price",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.SUPPORTED
    assert evidence.quote_verified is True


async def test_incorrect_quotation_against_real_fact_is_needs_review():
    org, _user = await _org()
    fact = await brand_facts.create(
        BrandFactCreate(
            organisation_id=org.id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc), quote="Nova Buds Pro deliver up to 8 hours of playback.",
        )
    )
    finding = await _make_finding(
        org.id, verdict=Verdict.VERIFIED, evidence_record_type="brand_fact", evidence_record_id=fact.id,
        # Claims a quote that does NOT actually appear in the fact's stored text.
        evidence_quote="This exact sentence was never written anywhere.",
        evidence_subject="Nova Buds Pro", evidence_attribute="battery_life",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.NEEDS_REVIEW
    assert evidence.quote_verified is False


async def test_missing_brand_fact_source_is_insufficient():
    org, _user = await _org()
    deleted_id = ObjectId()  # never created -> simulates a record deleted since analysis
    finding = await _make_finding(
        org.id, verdict=Verdict.VERIFIED, evidence_record_type="brand_fact", evidence_record_id=deleted_id,
        evidence_quote="anything", evidence_subject="Nova Buds Pro", evidence_attribute="battery_life",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.INSUFFICIENT
    assert evidence.unavailable is True


async def test_unsupported_verdict_is_insufficient_never_contradicted():
    org, _user = await _org()
    # No brand fact at all for this subject/attribute -- compare_claim_to_brand_facts
    # would have produced verdict=UNSUPPORTED exactly in this situation.
    finding = await _make_finding(
        org.id, verdict=Verdict.UNSUPPORTED, evidence_record_type=None, evidence_record_id=None,
        evidence_subject="Nova Widget", evidence_attribute="weight",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.INSUFFICIENT
    assert evidence.unavailable is True


async def test_contradicted_claim_finds_the_conflicting_fact():
    org, _user = await _org()
    fact = await brand_facts.create(
        BrandFactCreate(
            organisation_id=org.id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc), quote="8 hours of playback.",
        )
    )
    # verdict=CONTRADICTED never has an evidence_record_id (no single fact
    # matched the claimed "12 hours") -- only the subject/attribute hint.
    finding = await _make_finding(
        org.id, verdict=Verdict.CONTRADICTED, evidence_record_type=None, evidence_record_id=None,
        evidence_subject="Nova Buds Pro", evidence_attribute="battery_life",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.CONTRADICTED
    assert evidence.source_id == fact.id
    assert evidence.source_type == "brand_fact"
    assert "8" in (evidence.reason or "")


async def test_contradicted_with_no_facts_at_all_is_insufficient():
    org, _user = await _org()
    finding = await _make_finding(
        org.id, verdict=Verdict.CONTRADICTED, evidence_record_type=None, evidence_record_id=None,
        evidence_subject="Nonexistent Product", evidence_attribute="weight",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.INSUFFICIENT
    assert evidence.unavailable is True


# --- Terminology / claim-policy evidence ----------------------------------


async def test_terminology_rule_evidence_is_supported_with_no_pdf_page():
    org, _user = await _org()
    term = await terminology.create(
        TerminologyCreate(organisation_id=org.id, preferred_term="water-resistant", banned_variants=["waterproof"], reason="IPX4 only, not waterproof.")
    )
    finding = await _make_finding(
        org.id, category=FindingCategory.TERMINOLOGY, verdict=Verdict.CONTRADICTED,
        evidence_record_type="terminology", evidence_record_id=term.id, evidence_quote=term.reason,
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.SUPPORTED
    assert evidence.quote_verified is True
    assert evidence.page is None  # terminology rules are not PDF-backed -- must not be invented
    assert evidence.guideline_doc_id is None
    assert evidence.unavailable is False


async def test_deleted_terminology_record_is_insufficient():
    org, _user = await _org()
    finding = await _make_finding(
        org.id, category=FindingCategory.TERMINOLOGY, verdict=Verdict.CONTRADICTED,
        evidence_record_type="terminology", evidence_record_id=ObjectId(), evidence_quote="anything",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.INSUFFICIENT
    assert evidence.unavailable is True


async def test_claim_policy_evidence_is_supported():
    org, _user = await _org()
    policy = await claim_policies.create(
        ClaimPolicyCreate(organisation_id=org.id, pattern="guaranteed", status=ClaimPolicyStatus.BANNED)
    )
    finding = await _make_finding(
        org.id, category=FindingCategory.CLAIM, verdict=Verdict.CONTRADICTED,
        evidence_record_type="claim_policy", evidence_record_id=policy.id, evidence_quote="guaranteed",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.SUPPORTED
    assert evidence.quote_verified is True


# --- Guideline-chunk evidence (tone findings) -----------------------------


async def test_guideline_chunk_evidence_has_correct_real_pdf_page():
    org, _user = await _org()
    doc = await guideline_docs.create(
        GuidelineDocCreate(organisation_id=org.id, title="Tone Guide", filename="t.pdf", uploaded_by=_user.id, page_count=20, status=GuidelineDocStatus.READY)
    )
    chunk = await guideline_chunks.create(
        GuidelineChunkCreate(organisation_id=org.id, doc_id=doc.id, page=17, chunk_index=2, text="Keep copy upbeat and avoid unsubstantiated superlatives.")
    )
    finding = await _make_finding(
        org.id, category=FindingCategory.TONE, verdict=Verdict.NEEDS_REVIEW, source=FindingSource.LLM,
        evidence_record_type="guideline_chunk", evidence_record_id=chunk.id,
        evidence_quote="avoid unsubstantiated superlatives",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.SUPPORTED
    assert evidence.quote_verified is True
    assert evidence.page == 17  # the chunk's real PDF page, not chunk_index (2)
    assert evidence.guideline_doc_id == doc.id
    assert evidence.guideline_doc_title == "Tone Guide"
    assert evidence.source_text == chunk.text


async def test_guideline_chunk_quote_not_found_is_needs_review():
    org, _user = await _org()
    doc = await guideline_docs.create(
        GuidelineDocCreate(organisation_id=org.id, title="Tone Guide", filename="t.pdf", uploaded_by=_user.id, page_count=20, status=GuidelineDocStatus.READY)
    )
    chunk = await guideline_chunks.create(
        GuidelineChunkCreate(organisation_id=org.id, doc_id=doc.id, page=17, chunk_index=2, text="Keep copy upbeat.")
    )
    finding = await _make_finding(
        org.id, category=FindingCategory.TONE, verdict=Verdict.NEEDS_REVIEW, source=FindingSource.LLM,
        evidence_record_type="guideline_chunk", evidence_record_id=chunk.id,
        evidence_quote="this text is not in the chunk at all",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.NEEDS_REVIEW
    assert evidence.quote_verified is False


async def test_deleted_guideline_chunk_is_insufficient():
    org, _user = await _org()
    finding = await _make_finding(
        org.id, category=FindingCategory.TONE, verdict=Verdict.NEEDS_REVIEW, source=FindingSource.LLM,
        evidence_record_type="guideline_chunk", evidence_record_id=ObjectId(), evidence_quote="anything",
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.INSUFFICIENT
    assert evidence.unavailable is True


async def test_no_evidence_record_at_all_is_needs_review():
    org, _user = await _org()
    finding = await _make_finding(
        org.id, category=FindingCategory.TONE, verdict=Verdict.NEEDS_REVIEW, source=FindingSource.LLM,
        evidence_record_type=None, evidence_record_id=None,
    )

    evidence = await validate_finding_evidence(finding, organisation_id=org.id)
    assert evidence.status == EvidenceStatus.NEEDS_REVIEW
    assert evidence.unavailable is True
