"""Phase 5 analysis orchestrator -- ties together the deterministic rule
checks (always run), the AI-assisted checks (claim extraction + tone/
guideline-compliance, run when available and gracefully degraded when
not), content-hash caching, and findings persistence (replace-by-revision,
never accumulate duplicates).
"""

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel

from app.core.config import settings
from app.core.demo_context import DemoContext
from app.core.storage import ASSETS_DIR, SUBMISSIONS_DIR
from app.models import (
    AnalysisCache,
    AssetStatus,
    AssetType,
    BrandFact,
    FindingCategory,
    FindingCreate,
    FindingSeverity,
    FindingSource,
    Revision,
    Submission,
    SubmissionStatus,
    Verdict,
)
from app.repositories import assets, brand_facts, claim_policies, findings, guideline_chunks, guideline_docs, revisions, terminology
from app.services.ai import ProviderUnavailableError, get_embedding_provider, get_llm_provider
from app.services.analysis.claims import (
    ExtractedClaim,
    compare_claim_to_brand_facts,
    extract_claims_via_llm,
    extract_claims_via_rules,
)
from app.services.analysis.retrieval import top_k_chunks_by_similarity
from app.services.analysis.rules import RuleFinding, check_claim_policies, check_terminology
from app.services.analysis.tone import ToneFinding, analyze_tone_via_llm
from app.services.visual.accessibility import check_colour_contrast
from app.services.visual.colour_analysis import check_colour_consistency
from app.services.visual.logo_matching import check_logo_consistency


class ContentTooLongError(ValueError):
    pass


class AICheckOutcome(BaseModel):
    check: str
    reason: str


class AnalysisReport(BaseModel):
    submission_id: str
    revision_id: str
    revision_version: int
    findings_count: int
    ai_available: bool
    ai_checks_completed: list[str]
    ai_checks_unavailable: list[AICheckOutcome]
    used_cache: bool


_VERDICT_SEVERITY = {
    Verdict.CONTRADICTED: FindingSeverity.HIGH,
    Verdict.OUTDATED: FindingSeverity.MEDIUM,
    Verdict.UNSUPPORTED: FindingSeverity.MEDIUM,
    Verdict.NEEDS_REVIEW: FindingSeverity.LOW,
    Verdict.VERIFIED: FindingSeverity.LOW,
}


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def _config_version(organisation_id) -> str:
    """Model names + prompt version + a guideline-corpus fingerprint for
    this org. Any change to any of these produces a different string, so
    a stale cache simply never matches again -- no explicit eviction
    needed. The corpus fingerprint means uploading/changing a guideline
    doc invalidates previously-cached tone-analysis results for this org,
    since new reference material could change what the LLM would say."""
    docs = await guideline_docs.list(organisation_id=organisation_id, limit=1000)
    latest = max((d.updated_at for d in docs), default=None)
    guideline_fingerprint = f"{len(docs)}:{latest.isoformat() if latest else 'none'}"
    return (
        f"{settings.gemini_model}|{settings.gemini_embedding_model}|"
        f"{settings.analysis_prompt_version}|{guideline_fingerprint}"
    )


async def analyze_submission(submission: Submission, revision: Revision, context: DemoContext) -> AnalysisReport:
    """Analyses the given (already-frozen) revision and replaces its
    findings. Callers (the router) are responsible for confirming
    submission.status == PENDING_REVIEW and that `revision` is really the
    submission's current (frozen) one before calling this -- enforced
    again here defensively since persisting findings against a mutable
    draft would be meaningless (its content can still change)."""
    if submission.status != SubmissionStatus.PENDING_REVIEW:
        raise ValueError("Analysis is only permitted for submissions with status 'pending_review'.")

    content = revision.content
    if len(content) > settings.analysis_max_content_chars:
        raise ContentTooLongError(
            f"Content is {len(content)} characters, which exceeds the "
            f"{settings.analysis_max_content_chars}-character analysis limit."
        )

    org_id = submission.organisation_id
    now = datetime.now(timezone.utc)

    # Phase 7 Stage 2: record that THIS exact revision was analysed, right
    # now, unconditionally -- before any AI-availability branching below, so
    # a fully-degraded (rule-only) analysis still sets it. See the
    # docstring on Revision.analyzed_at (app/models/revision.py).
    await revisions.update(revision.id, {"analyzed_at": now}, organisation_id=org_id)

    # --- 1. Deterministic rule-based checks -- ALWAYS run, AI or no AI. ---
    term_rows = await terminology.list(organisation_id=org_id, limit=1000)
    policy_rows = await claim_policies.list(organisation_id=org_id, limit=1000)
    rule_findings: list[RuleFinding] = check_terminology(content, term_rows) + check_claim_policies(content, policy_rows)

    # --- 1b. Visual checks (Phase 7 Stage 3) -- only when this revision
    # carries an image. Pure local OpenCV, no AI-availability gate, same
    # "always run" treatment as the rule checks above. Missing/invalid
    # asset files are skipped safely, never raise. Appending to
    # rule_findings reuses the EXACT same FindingCreate-building and
    # replace-by-revision persistence below -- no new persistence path.
    if revision.image_path:
        image_file = SUBMISSIONS_DIR / revision.image_path
        if image_file.is_file():
            image_bytes = image_file.read_bytes()

            colour_assets = await assets.list(
                organisation_id=org_id,
                filter={"type": AssetType.COLOUR.value, "status": AssetStatus.APPROVED.value},
                limit=1000,
            )
            rule_findings += check_colour_consistency(image_bytes, colour_assets)

            logo_assets = await assets.list(organisation_id=org_id, filter={"type": AssetType.LOGO.value}, limit=1000)
            logo_pairs = []
            for logo_asset in logo_assets:
                if not logo_asset.file_path:
                    continue
                logo_file = ASSETS_DIR / logo_asset.file_path
                if logo_file.is_file():
                    logo_pairs.append((logo_asset, logo_file.read_bytes()))
            rule_findings += check_logo_consistency(image_bytes, logo_pairs)
            rule_findings += check_colour_contrast(image_bytes)

    all_facts = await brand_facts.list(organisation_id=org_id, limit=1000)
    facts_by_key: dict[tuple[str, str], list[BrandFact]] = {}
    for fact in all_facts:
        facts_by_key.setdefault((fact.subject, fact.attribute), []).append(fact)

    # --- 2. AI-assisted checks, with content-hash caching and per-call
    # degraded-mode fallback. ---------------------------------------------
    llm = get_llm_provider()
    embedder = get_embedding_provider()
    config_version = await _config_version(org_id)
    content_hash = _content_hash(content)

    cache = revision.analysis_cache
    cache_hit = cache is not None and cache.content_hash == content_hash and cache.config_version == config_version

    ai_checks_completed: list[str] = []
    ai_checks_unavailable: list[AICheckOutcome] = []
    evidence_chunks: list = []  # chunks available for tone-finding evidence linking, by index

    if cache_hit:
        extracted_claims = [ExtractedClaim.model_validate(c) for c in cache.extracted_claims]
        tone_findings = [ToneFinding.model_validate(f) for f in cache.tone_findings_raw]
        ai_checks_completed.append("claim_extraction (cached)")
        ai_checks_completed.append("tone_analysis (cached)")
        if cache.retrieved_chunk_ids:
            fetched = {
                c.id: c
                for c in await guideline_chunks.list(organisation_id=org_id, limit=5000)
                if c.id in set(cache.retrieved_chunk_ids)
            }
            evidence_chunks = [fetched[cid] for cid in cache.retrieved_chunk_ids if cid in fetched]
    else:
        # 2a. Claim extraction: LLM if available, else (or on failure) the
        # regex-based degraded fallback -- never skipped outright, per
        # section F ("run numerical brand-fact comparisons wherever claims
        # can be matched").
        # Phase 7 Stage 3 follow-up: empty/whitespace-only content (e.g. an
        # image-only submission) has nothing for claim extraction or tone
        # analysis to work on -- skip both real Gemini calls outright
        # rather than spending them on nothing. Visual analysis (above)
        # and every other check are unaffected.
        content_has_text = bool(content.strip())

        extracted_claims = []
        if not content_has_text:
            ai_checks_unavailable.append(
                AICheckOutcome(check="claim_extraction", reason="Content is empty; nothing to analyse.")
            )
        elif llm is not None:
            try:
                extracted_claims = await extract_claims_via_llm(llm, content, settings.analysis_max_output_tokens)
                ai_checks_completed.append("claim_extraction")
            except ProviderUnavailableError as exc:
                ai_checks_unavailable.append(AICheckOutcome(check="claim_extraction", reason=str(exc)))
        else:
            ai_checks_unavailable.append(
                AICheckOutcome(check="claim_extraction", reason="Gemini API key not configured.")
            )
        if "claim_extraction" not in ai_checks_completed:
            extracted_claims = extract_claims_via_rules(content, all_facts)

        # 2b. Retrieval + tone/guideline-compliance analysis.
        tone_findings = []
        if not content_has_text:
            ai_checks_unavailable.append(
                AICheckOutcome(check="retrieval", reason="Content is empty; nothing to analyse.")
            )
            ai_checks_unavailable.append(
                AICheckOutcome(check="tone_analysis", reason="Content is empty; nothing to analyse.")
            )
        elif embedder is None:
            ai_checks_unavailable.append(
                AICheckOutcome(check="retrieval", reason="Gemini API key not configured.")
            )
            ai_checks_unavailable.append(
                AICheckOutcome(
                    check="tone_analysis",
                    reason="Retrieval-based AI analysis could not be completed (no embedding provider configured).",
                )
            )
        else:
            try:
                [query_embedding] = await embedder.embed([content], input_type="query")
                all_chunks = await guideline_chunks.list(organisation_id=org_id, limit=5000)
                top = top_k_chunks_by_similarity(query_embedding, all_chunks, settings.analysis_retrieval_chunk_limit)
                evidence_chunks = [chunk for chunk, _score in top]
                ai_checks_completed.append("retrieval")
            except ProviderUnavailableError as exc:
                ai_checks_unavailable.append(AICheckOutcome(check="retrieval", reason=str(exc)))
                ai_checks_unavailable.append(
                    AICheckOutcome(
                        check="tone_analysis",
                        reason="Retrieval-based AI analysis could not be completed (embedding failure).",
                    )
                )

            if "retrieval" in ai_checks_completed:
                if llm is not None:
                    try:
                        tone_findings = await analyze_tone_via_llm(
                            llm, content, evidence_chunks, settings.analysis_max_output_tokens
                        )
                        ai_checks_completed.append("tone_analysis")
                    except ProviderUnavailableError as exc:
                        ai_checks_unavailable.append(AICheckOutcome(check="tone_analysis", reason=str(exc)))
                else:
                    ai_checks_unavailable.append(
                        AICheckOutcome(check="tone_analysis", reason="Gemini API key not configured.")
                    )

        # Cache ONLY when the full AI pipeline succeeded -- a partial
        # failure must never be cached as if complete, or a later retry
        # (once the provider recovers) would wrongly keep reusing it.
        if "claim_extraction" in ai_checks_completed and "tone_analysis" in ai_checks_completed:
            await revisions.update(
                revision.id,
                {
                    "analysis_cache": AnalysisCache(
                        content_hash=content_hash,
                        config_version=config_version,
                        extracted_claims=[c.model_dump() for c in extracted_claims],
                        tone_findings_raw=[f.model_dump() for f in tone_findings],
                        retrieved_chunk_ids=[c.id for c in evidence_chunks],
                        cached_at=now,
                    ).model_dump()
                },
                organisation_id=org_id,
            )

    # --- 3. Build finding documents. ---------------------------------
    new_finding_creates: list[FindingCreate] = []

    for rf in rule_findings:
        new_finding_creates.append(
            FindingCreate(
                organisation_id=org_id,
                revision_id=revision.id,
                category=FindingCategory(rf.category),
                severity=rf.severity,
                span_text=rf.span_text,
                explanation=rf.explanation,
                verdict=rf.verdict,
                evidence_record_type=rf.evidence_record_type,
                evidence_record_id=rf.evidence_record_id,
                evidence_quote=rf.evidence_quote,
                suggestion=rf.suggestion,
                source=FindingSource.RULE,
            )
        )

    for claim in extracted_claims:
        relevant = facts_by_key.get((claim.subject, claim.attribute), [])
        result = compare_claim_to_brand_facts(claim, relevant, now)
        matched = result.matched_fact
        new_finding_creates.append(
            FindingCreate(
                organisation_id=org_id,
                revision_id=revision.id,
                category=FindingCategory.FACT,
                severity=_VERDICT_SEVERITY[result.verdict],
                span_text=claim.source_quote,
                explanation=result.explanation,
                verdict=result.verdict,
                evidence_record_type="brand_fact" if matched else None,
                evidence_record_id=matched.id if matched else None,
                evidence_quote=(matched.quote if matched and matched.quote else None),
                # Phase 6: kept even when nothing matched (e.g. CONTRADICTED)
                # so app/services/evidence.py can re-query brand_facts for
                # this subject/attribute and show what the evidence actually
                # says, instead of having no lookup key at all.
                evidence_subject=claim.subject,
                evidence_attribute=claim.attribute,
                source=FindingSource.RULE,  # the verdict is always deterministic Python, even when the LLM did extraction
            )
        )

    for tf in tone_findings:
        evidence_chunk = (
            evidence_chunks[tf.guideline_chunk_index]
            if tf.guideline_chunk_index is not None and 0 <= tf.guideline_chunk_index < len(evidence_chunks)
            else None
        )
        new_finding_creates.append(
            FindingCreate(
                organisation_id=org_id,
                revision_id=revision.id,
                category=tf.category,
                severity=tf.severity,
                span_text=tf.span_text,
                explanation=tf.explanation,
                verdict=Verdict.NEEDS_REVIEW,  # never taken from the LLM -- see tone.py
                evidence_record_type="guideline_chunk" if evidence_chunk else None,
                evidence_record_id=evidence_chunk.id if evidence_chunk else None,
                evidence_quote=evidence_chunk.text if evidence_chunk else None,
                suggestion=tf.suggestion,
                source=FindingSource.LLM,
            )
        )

    # --- 4. Replace this revision's findings (never accumulate dupes). ---
    # Scoped by BOTH organisation_id and revision_id, so a delete can never
    # touch another org's or another revision's findings.
    await findings.delete_many({"organisation_id": org_id, "revision_id": revision.id})
    for fc in new_finding_creates:
        await findings.create(fc)

    return AnalysisReport(
        submission_id=str(submission.id),
        revision_id=str(revision.id),
        revision_version=revision.version,
        findings_count=len(new_finding_creates),
        ai_available=llm is not None or embedder is not None,
        ai_checks_completed=ai_checks_completed,
        ai_checks_unavailable=ai_checks_unavailable,
        used_cache=cache_hit,
    )
