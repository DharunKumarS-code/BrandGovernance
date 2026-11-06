"""Phase 6, Modules 1 (evidence, orchestration half), 4 (corrections) and 5
(accept/dismiss). Ties together app/services/evidence.py and
app/services/analysis/correction.py with persistence, and implements the
accept/dismiss state transition. Deliberately NOT a new collection: every
write here is a findings.update() onto the existing Finding document (plus
one audit_log.create() per decision) -- see the module docstrings on
app/models/finding.py for why.
"""

from datetime import datetime

from pymongo import ReturnDocument

from app.core.config import settings
from app.models import (
    CorrectionSuggestion,
    EvidenceReference,
    EvidenceStatus,
    Finding,
    FindingSource,
    FindingStatus,
    Revision,
)
from app.models.common import utcnow
from app.repositories import findings
from app.services.ai import ProviderUnavailableError, get_llm_provider
from app.services.analysis.correction import generate_correction_via_llm
from app.services.evidence import validate_finding_evidence


async def get_or_generate_evidence(finding: Finding, *, organisation_id, refresh: bool = False) -> Finding:
    """Returns `finding` with `.evidence` populated, computing and
    persisting it first if it's missing (or `refresh` is requested -- e.g.
    the underlying terminology/brand-fact record may have changed since
    the original analysis)."""
    if finding.evidence is not None and not refresh:
        return finding
    evidence = await validate_finding_evidence(finding, organisation_id=organisation_id)
    updated = await findings.update(finding.id, {"evidence": evidence.model_dump()}, organisation_id=organisation_id)
    return updated if updated is not None else finding


def _evidence_text_for_prompt(evidence: EvidenceReference) -> str:
    """Builds the TRUSTED evidence block handed to the correction LLM --
    only ever fields already present on a validated EvidenceReference,
    nothing re-derived or guessed here."""
    lines = [f"Evidence status: {evidence.status.value} -- {evidence.reason}"]
    if evidence.source_text:
        lines.append(f"Source text: {evidence.source_text}")
    if evidence.guideline_doc_title:
        page_str = f", page {evidence.page}" if evidence.page else ""
        lines.append(f"From: {evidence.guideline_doc_title}{page_str}")
    return "\n".join(lines)


def _fallback_correction(*, rationale: str, source: FindingSource = FindingSource.RULE) -> CorrectionSuggestion:
    """The one and only way a correction with corrected_span=None gets
    built -- used whenever evidence is insufficient or AI is unavailable.
    Never fabricates a fact; just says a human needs to look."""
    return CorrectionSuggestion(
        corrected_span=None,
        rationale=rationale,
        requires_human_review=True,
        source=source,
        generated_at=utcnow(),
        model=None,
    )


async def get_or_generate_correction(finding: Finding, revision: Revision, *, organisation_id, refresh: bool = False) -> Finding:
    """Returns `finding` with `.correction` populated, generating and
    persisting it first if missing (or `refresh`). Never calls the LLM
    when evidence is insufficient -- see _fallback_correction above and
    the INSUFFICIENT/unavailable branch below."""
    if finding.correction is not None and not refresh:
        return finding

    finding = await get_or_generate_evidence(finding, organisation_id=organisation_id)
    evidence = finding.evidence

    # 1. Reuse an existing deterministic/LLM-tone suggestion string from
    # Phase 5 (rules.py's terminology/claim-policy suggestions, or
    # tone.py's own ToneFinding.suggestion) rather than spending a fresh
    # LLM call re-deriving something already computed. These are either
    # fully deterministic (RULE) or were already produced by the same
    # guideline-grounded LLM pass (LLM) -- both trustworthy as-is.
    if finding.suggestion:
        correction = CorrectionSuggestion(
            corrected_span=finding.suggestion,
            rationale=evidence.reason if evidence else "Reused the suggestion already produced during analysis.",
            requires_human_review=(evidence is None or evidence.status != EvidenceStatus.SUPPORTED),
            source=finding.source,
            generated_at=utcnow(),
            model=None,
        )
    # 2. No evidence at all / evidence insufficient -> never ask the LLM to
    # invent a correction out of nothing.
    elif evidence is None or evidence.status == EvidenceStatus.INSUFFICIENT or evidence.unavailable:
        correction = _fallback_correction(
            rationale=(evidence.reason if evidence else "No evidence could be validated for this finding.")
            + " A correction cannot be safely generated without risking an invented fact."
        )
    else:
        llm = get_llm_provider()
        if llm is None:
            correction = _fallback_correction(
                rationale="The AI generation provider is not configured, so no correction could be generated. "
                "The finding and its evidence are still available for manual correction."
            )
        else:
            try:
                result = await generate_correction_via_llm(
                    llm,
                    full_content=revision.content,
                    span_text=finding.span_text,
                    explanation=finding.explanation,
                    evidence_text=_evidence_text_for_prompt(evidence),
                    max_output_tokens=settings.analysis_max_output_tokens,
                )
                correction = CorrectionSuggestion(
                    corrected_span=result.corrected_span,
                    rationale=result.rationale,
                    requires_human_review=result.requires_human_review or not result.corrected_span,
                    source=FindingSource.LLM,
                    generated_at=utcnow(),
                    model=settings.gemini_model,
                )
            except ProviderUnavailableError as exc:
                correction = _fallback_correction(
                    rationale=f"The AI generation provider is currently unavailable ({exc}); no correction was "
                    f"generated to avoid guessing. The finding and its evidence are still available for manual "
                    f"correction."
                )

    updated = await findings.update(finding.id, {"correction": correction.model_dump()}, organisation_id=organisation_id)
    return updated if updated is not None else finding


async def decide_suggestion(
    finding_id, *, organisation_id, user_id, decision: FindingStatus, dismiss_reason: str | None = None
) -> Finding | None:
    """Atomically transitions a finding from OPEN to ACCEPTED/DISMISSED.
    Returns None if the finding does not exist, belongs to another org, or
    was already decided -- the filter below only ever matches an OPEN
    finding in this exact org, so two concurrent accept/dismiss calls (or
    a duplicate click) can never both succeed: MongoDB guarantees a single
    document update is atomic, so only the first racer's filter matches."""
    now: datetime = utcnow()
    changes: dict = {"status": decision, "decided_by": user_id, "decided_at": now, "updated_at": now}
    if decision == FindingStatus.DISMISSED:
        changes["dismiss_reason"] = dismiss_reason

    doc = await findings.collection.find_one_and_update(
        {"_id": finding_id, "organisation_id": organisation_id, "status": FindingStatus.OPEN},
        {"$set": changes},
        return_document=ReturnDocument.AFTER,
    )
    return Finding.model_validate(doc) if doc else None


def build_corrected_preview(content: str, finding: Finding) -> str | None:
    """A pure, read-only computation -- never persisted, never applied
    automatically. Returns the revision's content with this ONE finding's
    span replaced by its accepted correction, so the caller (the API/UI)
    can hand it to the EXISTING draft-edit/revise workflow for the user to
    actually submit. Returns None when there is no usable correction, or
    the exact span can no longer be found in the content (e.g. a stale
    finding against edited content)."""
    if finding.correction is None or not finding.correction.corrected_span:
        return None
    if finding.span_text not in content:
        return None
    return content.replace(finding.span_text, finding.correction.corrected_span, 1)
