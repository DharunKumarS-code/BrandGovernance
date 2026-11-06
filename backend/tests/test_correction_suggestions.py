"""Phase 6, Module 4 tests: app/services/suggestions.py's
get_or_generate_correction() (and, at the end, the HTTP endpoint that
wraps it). Uses tests/ai_fakes.py's FakeLLMProvider -- no real Gemini
calls, fully deterministic, exactly like the existing Phase 5 analysis
tests (tests/test_analysis_endpoint.py).
"""

from datetime import datetime, timezone

from bson import ObjectId

import app.services.suggestions as suggestions_module
from app.models import (
    BrandFactCreate,
    FindingCategory,
    FindingCreate,
    FindingSeverity,
    FindingSource,
    OrganisationCreate,
    RevisionCreate,
    TerminologyCreate,
    UserCreate,
    UserRole,
    Verdict,
)
from app.repositories import brand_facts, findings, organisations, revisions, terminology, users
from app.services.suggestions import get_or_generate_correction

from tests.ai_fakes import FakeLLMProvider

DUMMY_SUBMISSION_ID = ObjectId()


async def _org_and_revision(content: str = "Some submitted content."):
    org = await organisations.create(OrganisationCreate(name="Correction Test Org"))
    user = await users.create(UserCreate(organisation_id=org.id, name="Tester", email="correction-test@example.com", role=UserRole.ADMIN))
    revision = await revisions.create(
        RevisionCreate(organisation_id=org.id, submission_id=DUMMY_SUBMISSION_ID, version=1, content=content, content_type="text/plain", author_id=user.id)
    )
    return org, user, revision


async def _make_finding(org_id, revision_id, **overrides):
    defaults = dict(
        organisation_id=org_id, revision_id=revision_id, category=FindingCategory.FACT, severity=FindingSeverity.MEDIUM,
        span_text="12 hours", explanation="Claimed battery life does not match any recorded value.",
        verdict=Verdict.CONTRADICTED, source=FindingSource.RULE,
    )
    defaults.update(overrides)
    return await findings.create(FindingCreate(**defaults))


# --- Reusing an existing deterministic/LLM-tone suggestion ----------------


async def test_rule_finding_reuses_existing_suggestion_without_calling_llm(monkeypatch):
    org, _user, revision = await _org_and_revision()
    term = await terminology.create(
        TerminologyCreate(organisation_id=org.id, preferred_term="water-resistant", banned_variants=["waterproof"], reason="IPX4 only, not waterproof.")
    )
    finding = await _make_finding(
        org.id, revision.id, category=FindingCategory.TERMINOLOGY, verdict=Verdict.CONTRADICTED,
        span_text="waterproof", evidence_record_type="terminology", evidence_record_id=term.id,
        evidence_quote=term.reason, suggestion="Use 'water-resistant' instead.",
    )

    fake_llm = FakeLLMProvider(fail=True)  # would raise immediately if ever called
    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: fake_llm)

    updated = await get_or_generate_correction(finding, revision, organisation_id=org.id)

    assert fake_llm.calls == []  # never called -- reused the deterministic suggestion
    assert updated.correction is not None
    assert updated.correction.corrected_span == "Use 'water-resistant' instead."
    assert updated.correction.source == FindingSource.RULE
    assert updated.correction.requires_human_review is False  # evidence was SUPPORTED


# --- Insufficient evidence must never reach the LLM -----------------------


async def test_insufficient_evidence_never_calls_llm_and_requires_review(monkeypatch):
    org, _user, revision = await _org_and_revision()
    # No brand fact exists at all -> verdict UNSUPPORTED -> evidence INSUFFICIENT.
    finding = await _make_finding(
        org.id, revision.id, verdict=Verdict.UNSUPPORTED, evidence_subject="Ghost Product", evidence_attribute="weight",
    )

    fake_llm = FakeLLMProvider(fail=True)
    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: fake_llm)

    updated = await get_or_generate_correction(finding, revision, organisation_id=org.id)

    assert fake_llm.calls == []
    assert updated.correction.corrected_span is None  # never invented
    assert updated.correction.requires_human_review is True


# --- Sufficient evidence + a real (fake) LLM call --------------------------


async def test_fact_finding_with_sufficient_evidence_uses_llm_correction(monkeypatch):
    org, _user, revision = await _org_and_revision(content="Nova Buds Pro deliver 12 hours of non-stop playback.")
    await brand_facts.create(
        BrandFactCreate(
            organisation_id=org.id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours",
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc), quote="8 hours of playback.",
        )
    )
    finding = await _make_finding(
        org.id, revision.id, verdict=Verdict.CONTRADICTED, span_text="12 hours",
        evidence_subject="Nova Buds Pro", evidence_attribute="battery_life",
    )

    fake_llm = FakeLLMProvider(
        responses={"corrected_span": {"corrected_span": "8 hours", "rationale": "The brand fact records 8 hours, not 12.", "requires_human_review": False}}
    )
    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: fake_llm)

    updated = await get_or_generate_correction(finding, revision, organisation_id=org.id)

    assert len(fake_llm.calls) == 1
    assert updated.correction.corrected_span == "8 hours"
    assert updated.correction.source == FindingSource.LLM
    assert updated.correction.requires_human_review is False
    assert updated.evidence.status.value == "contradicted"  # evidence was computed as a side effect too


async def test_llm_requires_human_review_flag_is_preserved_even_with_a_span(monkeypatch):
    org, _user, revision = await _org_and_revision()
    await brand_facts.create(
        BrandFactCreate(organisation_id=org.id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours", valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc))
    )
    finding = await _make_finding(org.id, revision.id, verdict=Verdict.CONTRADICTED, evidence_subject="Nova Buds Pro", evidence_attribute="battery_life")

    fake_llm = FakeLLMProvider(
        responses={"corrected_span": {"corrected_span": "8 hours", "rationale": "Ambiguous phrasing.", "requires_human_review": True}}
    )
    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: fake_llm)

    updated = await get_or_generate_correction(finding, revision, organisation_id=org.id)
    assert updated.correction.requires_human_review is True  # the model's own flag is never overridden to False


async def test_malformed_llm_response_falls_back_without_fabricating(monkeypatch):
    org, _user, revision = await _org_and_revision()
    await brand_facts.create(
        BrandFactCreate(organisation_id=org.id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours", valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc))
    )
    finding = await _make_finding(org.id, revision.id, verdict=Verdict.CONTRADICTED, evidence_subject="Nova Buds Pro", evidence_attribute="battery_life")

    # Missing the required "rationale"/"requires_human_review" fields.
    fake_llm = FakeLLMProvider(responses={"corrected_span": {"corrected_span": "8 hours"}})
    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: fake_llm)

    updated = await get_or_generate_correction(finding, revision, organisation_id=org.id)
    assert updated.correction.corrected_span is None  # schema-invalid output is never trusted
    assert updated.correction.requires_human_review is True


async def test_llm_provider_failure_falls_back_without_fabricating(monkeypatch):
    org, _user, revision = await _org_and_revision()
    await brand_facts.create(
        BrandFactCreate(organisation_id=org.id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours", valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc))
    )
    finding = await _make_finding(org.id, revision.id, verdict=Verdict.CONTRADICTED, evidence_subject="Nova Buds Pro", evidence_attribute="battery_life")

    fake_llm = FakeLLMProvider(fail=True)
    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: fake_llm)

    updated = await get_or_generate_correction(finding, revision, organisation_id=org.id)
    assert updated.correction.corrected_span is None
    assert updated.correction.requires_human_review is True


# --- Degraded mode: no AI provider configured at all -----------------------


async def test_degraded_mode_no_llm_configured_falls_back_cleanly(monkeypatch):
    org, _user, revision = await _org_and_revision()
    await brand_facts.create(
        BrandFactCreate(organisation_id=org.id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours", valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc))
    )
    finding = await _make_finding(org.id, revision.id, verdict=Verdict.CONTRADICTED, evidence_subject="Nova Buds Pro", evidence_attribute="battery_life")

    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: None)

    updated = await get_or_generate_correction(finding, revision, organisation_id=org.id)
    assert updated.correction.corrected_span is None
    assert updated.correction.requires_human_review is True
    assert "not configured" in updated.correction.rationale.lower()


async def test_cached_correction_is_not_regenerated_without_refresh(monkeypatch):
    org, _user, revision = await _org_and_revision()
    term = await terminology.create(TerminologyCreate(organisation_id=org.id, preferred_term="X", banned_variants=["Y"], reason="reason"))
    finding = await _make_finding(
        org.id, revision.id, category=FindingCategory.TERMINOLOGY, verdict=Verdict.CONTRADICTED,
        evidence_record_type="terminology", evidence_record_id=term.id, evidence_quote="reason", suggestion="Use X.",
    )

    fake_llm = FakeLLMProvider(fail=True)
    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: fake_llm)

    first = await get_or_generate_correction(finding, revision, organisation_id=org.id)
    second = await get_or_generate_correction(first, revision, organisation_id=org.id)
    assert second.correction.corrected_span == first.correction.corrected_span
    assert fake_llm.calls == []
