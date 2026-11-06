"""Phase 6, Module 1: evidence validation.

Takes a persisted Finding (already produced by the Phase 5 analysis
pipeline -- app/services/analysis/orchestrator.py) and checks whether the
evidence it cites actually backs it up: does the referenced brand-fact/
terminology/claim-policy/guideline-chunk record still exist, and -- where
a quotation is involved -- does that exact text still appear in the
record's own stored text? This module NEVER invents a quote, a page
number, or an evidence record: every field on the returned
EvidenceReference either comes directly from a DB record this finding
already pointed at, or is explicitly None/`unavailable=True` when no such
record can be found.

EvidenceStatus is deliberately a separate dimension from Verdict (see the
docstring on Verdict in app/models/finding.py) -- this module answers "how
well is this conclusion supported", never "was the conclusion correct".
"""

import re

from app.models import BrandFact, EvidenceReference, EvidenceStatus, Finding, FindingCategory, Verdict
from app.repositories import assets, brand_facts, claim_policies, guideline_chunks, guideline_docs, terminology


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _quote_appears_in(quote: str | None, source_text: str | None) -> bool:
    """Verbatim (whitespace/case-insensitive) substring check -- the only
    thing this module ever does to "verify" a quotation. Never fuzzy-
    matched, never LLM-judged: a quote either really is in the stored text
    or it isn't."""
    if not quote or not source_text:
        return False
    return _normalize(quote) in _normalize(source_text)


async def _validate_rule_record_evidence(finding: Finding, organisation_id, *, repo, label: str) -> EvidenceReference:
    if finding.evidence_record_id is None:
        return EvidenceReference(
            status=EvidenceStatus.INSUFFICIENT,
            reason=f"No {label} record id was attached to this finding.",
            unavailable=True,
        )
    record = await repo.get(finding.evidence_record_id, organisation_id=organisation_id)
    if record is None:
        return EvidenceReference(
            status=EvidenceStatus.INSUFFICIENT,
            reason=f"The {label} rule this finding cited no longer exists -- it may have been edited or deleted "
            f"since this analysis ran.",
            unavailable=True,
            source_type=finding.evidence_record_type,
            source_id=finding.evidence_record_id,
        )
    # rules.py (Phase 5) built evidence_quote directly FROM this exact
    # record, so this is correct by construction -- still verified
    # defensively rather than assumed, since the record may have been
    # edited since the finding was created.
    record_text = getattr(record, "reason", None) or getattr(record, "required_disclaimer", None) or getattr(record, "pattern", None) or ""
    quote = finding.evidence_quote
    verified = _quote_appears_in(quote, record_text)
    return EvidenceReference(
        status=EvidenceStatus.SUPPORTED,
        reason=f"Backed by this organisation's {label} rule. Governance rules of this kind are not sourced from "
        f"a PDF page, so no document/page reference is available for them.",
        source_type=finding.evidence_record_type,
        source_id=record.id,
        source_text=record_text or None,
        quote=quote,
        quote_verified=verified,
    )


async def _validate_guideline_chunk_evidence(finding: Finding, organisation_id) -> EvidenceReference:
    if finding.evidence_record_id is None:
        return EvidenceReference(
            status=EvidenceStatus.NEEDS_REVIEW,
            reason="This finding references guideline material in general, but no specific excerpt id was "
            "recorded; human review is required.",
            unavailable=True,
        )
    chunk = await guideline_chunks.get(finding.evidence_record_id, organisation_id=organisation_id)
    if chunk is None:
        return EvidenceReference(
            status=EvidenceStatus.INSUFFICIENT,
            reason="The guideline excerpt this finding cited no longer exists (the source document may have "
            "been reprocessed or deleted since this analysis ran).",
            unavailable=True,
            source_type="guideline_chunk",
            source_id=finding.evidence_record_id,
        )
    doc = await guideline_docs.get(chunk.doc_id, organisation_id=organisation_id)
    doc_title = doc.title if doc else None
    quote = finding.evidence_quote

    if quote:
        verified = _quote_appears_in(quote, chunk.text)
        if verified:
            status, reason = EvidenceStatus.SUPPORTED, "The cited quotation was confirmed, verbatim, in the stored guideline text."
        else:
            status, reason = (
                EvidenceStatus.NEEDS_REVIEW,
                "The cited quotation could not be confirmed verbatim in the stored guideline text; human review "
                "is required before relying on it.",
            )
    else:
        verified = False
        status, reason = EvidenceStatus.SUPPORTED, "Based generally on this retrieved guideline excerpt; no specific quotation was cited."

    return EvidenceReference(
        status=status,
        reason=reason,
        source_type="guideline_chunk",
        source_id=chunk.id,
        guideline_doc_id=chunk.doc_id,
        guideline_doc_title=doc_title,
        page=chunk.page,  # the real, original PDF page -- never a chunk index
        source_text=chunk.text,
        quote=quote,
        quote_verified=verified,
    )


async def _fact_record_evidence(fact: BrandFact, organisation_id, *, quote: str | None) -> tuple[str | None, bool]:
    doc_title = None
    if fact.source_doc_id:
        doc = await guideline_docs.get(fact.source_doc_id, organisation_id=organisation_id)
        doc_title = doc.title if doc else None
    verified = _quote_appears_in(quote, fact.quote)
    return doc_title, verified


async def _validate_fact_evidence(finding: Finding, organisation_id) -> EvidenceReference:
    if finding.verdict == Verdict.UNSUPPORTED:
        # By construction (app/services/analysis/claims.py), UNSUPPORTED
        # means "no brand fact exists for this subject/attribute at all" --
        # this is NOT evidence the claim is false, just that nothing can
        # confirm or deny it. Must map to INSUFFICIENT, never CONTRADICTED.
        return EvidenceReference(
            status=EvidenceStatus.INSUFFICIENT,
            reason=f"No brand fact is recorded for {finding.evidence_subject or 'this subject'} / "
            f"{finding.evidence_attribute or 'this attribute'}; the claim cannot be checked either way. "
            f"This does not mean the claim is false.",
            unavailable=True,
        )

    if finding.verdict == Verdict.NEEDS_REVIEW:
        return EvidenceReference(
            status=EvidenceStatus.NEEDS_REVIEW,
            reason="The claimed unit could not be confidently compared against the units recorded for this "
            "subject/attribute; human review is required.",
            unavailable=finding.evidence_record_id is None,
        )

    if finding.verdict in (Verdict.VERIFIED, Verdict.OUTDATED):
        if finding.evidence_record_id is None:
            return EvidenceReference(
                status=EvidenceStatus.INSUFFICIENT,
                reason="No specific brand fact id was recorded for this finding.",
                unavailable=True,
            )
        fact = await brand_facts.get(finding.evidence_record_id, organisation_id=organisation_id)
        if fact is None:
            return EvidenceReference(
                status=EvidenceStatus.INSUFFICIENT,
                reason="The brand fact record this finding cited has since been deleted or changed; evidence "
                "can no longer be confirmed.",
                unavailable=True,
                source_type="brand_fact",
                source_id=finding.evidence_record_id,
            )
        doc_title, verified = await _fact_record_evidence(fact, organisation_id, quote=finding.evidence_quote)
        status = EvidenceStatus.SUPPORTED if (not finding.evidence_quote or verified) else EvidenceStatus.NEEDS_REVIEW
        reason = (
            "The matched brand fact record confirms this finding."
            if status == EvidenceStatus.SUPPORTED
            else "The matched brand fact exists, but its stored quotation could not confirm the exact text "
            "cited; human review is recommended."
        )
        return EvidenceReference(
            status=status,
            reason=reason,
            source_type="brand_fact",
            source_id=fact.id,
            guideline_doc_id=fact.source_doc_id,
            guideline_doc_title=doc_title,
            page=fact.page,
            source_text=fact.quote,
            quote=finding.evidence_quote,
            quote_verified=verified,
        )

    # verdict == CONTRADICTED: compare_claim_to_brand_facts() found facts for
    # this subject/attribute but none matched the claimed value, so there is
    # no single evidence_record_id -- re-query by the subject/attribute hint
    # (Phase 6 addition, set by the orchestrator) to show what the evidence
    # actually says, so "evidence conflicts with the finding" is a real,
    # cited fact rather than an unsupported assertion.
    if not finding.evidence_subject or not finding.evidence_attribute:
        return EvidenceReference(
            status=EvidenceStatus.INSUFFICIENT,
            reason="No subject/attribute reference was recorded for this contradicted claim; evidence cannot "
            "be looked up.",
            unavailable=True,
        )
    candidates = await brand_facts.list(
        organisation_id=organisation_id,
        filter={"subject": finding.evidence_subject, "attribute": finding.evidence_attribute},
        limit=50,
    )
    if not candidates:
        return EvidenceReference(
            status=EvidenceStatus.INSUFFICIENT,
            reason=f"No brand fact is recorded for {finding.evidence_subject} / {finding.evidence_attribute} at "
            f"all; there is nothing to contradict against.",
            unavailable=True,
        )
    # Prefer the currently-valid fact if there is one; otherwise the most
    # recent. Either way this is a real, existing record -- never invented.
    current = [f for f in candidates if f.valid_to is None]
    fact = current[0] if current else sorted(candidates, key=lambda f: f.valid_from, reverse=True)[0]
    doc_title, _verified = await _fact_record_evidence(fact, organisation_id, quote=finding.evidence_quote)
    unit_str = f" {fact.unit}" if fact.unit else ""
    return EvidenceReference(
        status=EvidenceStatus.CONTRADICTED,
        reason=f"The claimed value conflicts with the recorded brand fact ({fact.value}{unit_str}).",
        source_type="brand_fact",
        source_id=fact.id,
        guideline_doc_id=fact.source_doc_id,
        guideline_doc_title=doc_title,
        page=fact.page,
        source_text=fact.quote,
        quote=finding.evidence_quote,
        quote_verified=False,  # the quote is the SUBMITTED claim, not this fact's own text -- never "verified" against it
    )


async def _validate_asset_evidence(finding: Finding, organisation_id) -> EvidenceReference:
    """Phase 7 Stage 4: evidence for visual (logo/colour) findings, which
    cite a brand asset record rather than a PDF/rule record."""
    if finding.evidence_record_id is None:
        return EvidenceReference(
            status=EvidenceStatus.INSUFFICIENT, reason="No brand asset id was attached to this finding.", unavailable=True
        )
    asset = await assets.get(finding.evidence_record_id, organisation_id=organisation_id)
    if asset is None:
        return EvidenceReference(
            status=EvidenceStatus.INSUFFICIENT,
            reason="The brand asset this finding cited no longer exists -- it may have been deleted since "
            "this analysis ran.",
            unavailable=True,
            source_type="asset",
            source_id=finding.evidence_record_id,
        )
    source_text = f"{asset.type.value.capitalize()} '{asset.name}' ({asset.status.value})"
    quote = finding.evidence_quote
    verified = bool(quote) and asset.name in (quote or "")
    return EvidenceReference(
        status=EvidenceStatus.SUPPORTED,
        reason="Backed by this organisation's brand asset record. Visual evidence of this kind is not "
        "sourced from a PDF page, so no document/page reference is available for it.",
        source_type="asset",
        source_id=asset.id,
        source_text=source_text,
        quote=quote,
        quote_verified=verified,
    )


async def validate_finding_evidence(finding: Finding, *, organisation_id) -> EvidenceReference:
    """Retrieves and validates the evidence behind one finding. Always
    returns an EvidenceReference -- never raises for "no evidence found";
    that is itself represented as status=INSUFFICIENT/unavailable=True."""
    if finding.category == FindingCategory.FACT:
        return await _validate_fact_evidence(finding, organisation_id)

    if finding.evidence_record_type == "terminology":
        return await _validate_rule_record_evidence(finding, organisation_id, repo=terminology, label="terminology")
    if finding.evidence_record_type == "claim_policy":
        return await _validate_rule_record_evidence(finding, organisation_id, repo=claim_policies, label="claim policy")
    if finding.evidence_record_type == "guideline_chunk":
        return await _validate_guideline_chunk_evidence(finding, organisation_id)
    if finding.evidence_record_type == "asset":
        return await _validate_asset_evidence(finding, organisation_id)

    # No evidence record of any kind -- e.g. a general LLM tone observation
    # with no specific guideline excerpt (guideline_chunk_index was null).
    # Not false, just not evidence-backed: a human should look at it.
    return EvidenceReference(
        status=EvidenceStatus.NEEDS_REVIEW,
        reason="This finding is a general observation with no specific evidence record attached; human review "
        "is required.",
        unavailable=True,
    )
