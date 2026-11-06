"""Unit tests for the pure rule-based checks (no LLM) -- terminology and
claim-policy -- which must always run regardless of AI availability."""

from app.models import ClaimPolicyCreate, ClaimPolicyStatus, TerminologyCreate, Verdict
from app.repositories import claim_policies, terminology
from app.services.analysis.rules import check_claim_policies, check_terminology


async def test_terminology_flags_banned_variant(demo_headers):
    _headers, org, _user = demo_headers
    term = await terminology.create(
        TerminologyCreate(
            organisation_id=org.id,
            preferred_term="water-resistant",
            banned_variants=["waterproof", "water proof"],
            reason="Product is IPX4, not waterproof.",
        )
    )
    content = "Nova Buds Pro are completely waterproof, so wear them in the shower."

    findings = check_terminology(content, [term])
    assert len(findings) == 1
    assert findings[0].verdict == Verdict.CONTRADICTED
    assert findings[0].evidence_record_id == term.id
    assert "waterproof" in findings[0].span_text.lower()


async def test_terminology_case_insensitive_and_no_false_positive(demo_headers):
    _headers, org, _user = demo_headers
    term = await terminology.create(
        TerminologyCreate(organisation_id=org.id, preferred_term="X", banned_variants=["banned phrase"], reason="r")
    )
    assert len(check_terminology("This has a BANNED PHRASE in it.", [term])) == 1
    assert len(check_terminology("This is totally fine content.", [term])) == 0


async def test_claim_policy_banned_pattern_is_contradicted(demo_headers):
    _headers, org, _user = demo_headers
    policy = await claim_policies.create(
        ClaimPolicyCreate(organisation_id=org.id, pattern="clinically proven", status=ClaimPolicyStatus.BANNED)
    )
    content = "Nova Home Hub is clinically proven to improve your sleep by 40%."

    findings = check_claim_policies(content, [policy])
    assert len(findings) == 1
    assert findings[0].verdict == Verdict.CONTRADICTED
    assert findings[0].severity.value == "high"


async def test_claim_policy_needs_evidence_pattern_is_needs_review(demo_headers):
    _headers, org, _user = demo_headers
    policy = await claim_policies.create(
        ClaimPolicyCreate(
            organisation_id=org.id,
            pattern="#1",
            status=ClaimPolicyStatus.NEEDS_EVIDENCE,
            required_disclaimer="Must cite the specific ranking source and date.",
        )
    )
    content = "The #1 earbuds in the world."

    findings = check_claim_policies(content, [policy])
    assert len(findings) == 1
    assert findings[0].verdict == Verdict.NEEDS_REVIEW
    assert findings[0].suggestion == "Must cite the specific ranking source and date."


async def test_claim_policy_approved_pattern_produces_no_finding(demo_headers):
    _headers, org, _user = demo_headers
    policy = await claim_policies.create(
        ClaimPolicyCreate(organisation_id=org.id, pattern="eco-friendly", status=ClaimPolicyStatus.APPROVED)
    )
    findings = check_claim_policies("Our eco-friendly packaging.", [policy])
    assert findings == []
