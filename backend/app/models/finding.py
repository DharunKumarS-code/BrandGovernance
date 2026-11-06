from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.models.common import OrgScopedCreate, OrgScopedModel, PyObjectId


class FindingCategory(StrEnum):
    FACT = "fact"
    TERMINOLOGY = "terminology"
    CLAIM = "claim"
    TONE = "tone"
    VISUAL = "visual"
    ACCESSIBILITY = "accessibility"


class FindingSeverity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Verdict(StrEnum):
    """Five-way verdict. UNSUPPORTED is distinct from CONTRADICTED and must
    never be collapsed into a simple true/false — "we found no evidence" is
    not the same claim as "we found evidence it's wrong". Phase 6 adds a
    SEPARATE, orthogonal dimension (EvidenceStatus, below) rather than
    touching this enum at all -- a verdict is "what we concluded about the
    submitted claim"; an evidence status is "how well-supported is the
    evidence behind that conclusion". Do not redefine or extend this enum
    for evidence-validation purposes."""

    CONTRADICTED = "contradicted"
    OUTDATED = "outdated"
    UNSUPPORTED = "unsupported"
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"


class FindingSource(StrEnum):
    RULE = "rule"
    LLM = "llm"
    VISION = "vision"


class FindingStatus(StrEnum):
    """Phase 6 reuses this exact enum as the correction-suggestion lifecycle
    (OPEN == "pending", not yet decided) rather than introducing a second,
    parallel pending/accepted/dismissed state machine -- a finding and its
    suggestion are decided together, by the same user action."""

    OPEN = "open"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class EvidenceStatus(StrEnum):
    """Phase 6: how well the evidence actually backs a finding -- a
    dimension orthogonal to Verdict (see the note on Verdict above). This
    is never surfaced as or confused with a Verdict value."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    NEEDS_REVIEW = "needs_review"


class EvidenceReference(BaseModel):
    """Phase 6: the result of validating one finding's cited evidence --
    produced by app/services/evidence.py, never hand-built elsewhere, and
    never containing an invented quote or page number. `quote` is only ever
    copied from the finding it was validated for (never generated), and
    `quote_verified` is only True when that exact text was found, verbatim
    (case/whitespace-insensitively), inside `source_text`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: EvidenceStatus
    reason: str
    source_type: str | None = None  # "brand_fact" | "terminology" | "claim_policy" | "guideline_chunk"
    source_id: PyObjectId | None = None
    guideline_doc_id: PyObjectId | None = None
    guideline_doc_title: str | None = None
    # Real, original PDF page number (1-indexed, as extracted by
    # app/services/pdf_processing.py) -- never a chunk index. None when this
    # evidence type has no PDF page at all (terminology/claim-policy rules
    # are not PDF-backed), which the API/UI must render as "unavailable",
    # never as page 0 or an omitted-but-implied page.
    page: int | None = None
    source_text: str | None = None
    quote: str | None = None
    quote_verified: bool = False
    unavailable: bool = False


class CorrectionSuggestion(BaseModel):
    """Phase 6: an AI- or rule-derived correction for one finding's
    span_text. `corrected_span` is None whenever a safe correction cannot be
    produced without inventing facts -- see app/services/suggestions.py and
    app/services/analysis/correction.py. Acceptance/dismissal state is
    deliberately NOT duplicated here -- it lives on the parent Finding's
    existing `status`/`dismiss_reason`/`decided_by`/`decided_at` fields,
    since a finding and its suggestion are always decided as one unit."""

    corrected_span: str | None = None
    rationale: str
    requires_human_review: bool
    source: FindingSource  # RULE (reused existing rules.py/tone.py suggestion) or LLM (freshly generated)
    generated_at: datetime
    model: str | None = None  # the Gemini model used, when source == LLM


class FindingCreate(OrgScopedCreate):
    revision_id: PyObjectId
    category: FindingCategory
    severity: FindingSeverity
    span_text: str
    explanation: str
    verdict: Verdict
    evidence_record_type: str | None = None
    # Phase 5: a finding with verdict=UNSUPPORTED or a general tone/
    # messaging observation may genuinely have no single backing DB record
    # (that's what "unsupported" means -- no evidence either way) or no
    # one specific chunk it came from. Required through Phase 1-4 because
    # every finding back then was assumed FACT-category and brand-fact-
    # backed; loosened here rather than forcing a misleading placeholder id.
    evidence_record_id: PyObjectId | None = None
    evidence_quote: str | None = None
    # Phase 6: only ever set for category=FACT, so evidence validation can
    # re-query brand_facts for a CONTRADICTED claim -- which, by
    # compare_claim_to_brand_facts' own design, matches no single existing
    # fact record and therefore has no evidence_record_id to look up.
    # Without these, "evidence conflicts with the finding" could never be
    # shown for exactly the verdict it's most relevant to.
    evidence_subject: str | None = None
    evidence_attribute: str | None = None
    suggestion: str | None = None
    source: FindingSource
    status: FindingStatus = FindingStatus.OPEN
    dismiss_reason: str | None = None
    # Phase 6 additions -- all optional/absent-by-default so every existing
    # Finding document (and every Phase 1-5 code path that builds a
    # FindingCreate without them) remains valid with no migration.
    evidence: EvidenceReference | None = None
    correction: CorrectionSuggestion | None = None
    decided_by: PyObjectId | None = None
    decided_at: datetime | None = None


class Finding(OrgScopedModel):
    revision_id: PyObjectId
    category: FindingCategory
    severity: FindingSeverity
    span_text: str
    explanation: str
    verdict: Verdict
    evidence_record_type: str | None = None
    evidence_record_id: PyObjectId | None = None
    evidence_quote: str | None = None
    evidence_subject: str | None = None
    evidence_attribute: str | None = None
    suggestion: str | None = None
    source: FindingSource
    status: FindingStatus
    dismiss_reason: str | None = None
    evidence: EvidenceReference | None = None
    correction: CorrectionSuggestion | None = None
    decided_by: PyObjectId | None = None
    decided_at: datetime | None = None
