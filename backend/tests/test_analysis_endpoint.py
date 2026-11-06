"""Integration tests for POST /api/submissions/{id}/analyze and
GET /api/submissions/{id}/findings -- gating, findings persistence/
replacement, caching, degraded mode, prompt-injection schema rejection,
and organisation isolation.

Uses FakeLLMProvider/FakeEmbeddingProvider (tests/ai_fakes.py) monkeypatched
into app.services.analysis.orchestrator's module namespace -- no real
network calls, fully deterministic.
"""

from datetime import datetime, timezone

import app.services.analysis.orchestrator as orchestrator_module
from app.models import BrandFactCreate, ClaimPolicyCreate, ClaimPolicyStatus, OrganisationCreate, TerminologyCreate, UserCreate, UserRole
from app.repositories import brand_facts, claim_policies, organisations, revisions, terminology, users

from tests.ai_fakes import FakeEmbeddingProvider, FakeLLMProvider

PLANTED_MISTAKE_AD = (
    "Nova Buds Pro deliver 12 hours of non-stop playback. Get them for just $129 today only -- "
    "and they're completely waterproof! Clinically proven to feel great."
)


async def _seed_minimal_nova(org_id):
    await brand_facts.create(
        BrandFactCreate(
            organisation_id=org_id, subject="Nova Buds Pro", attribute="battery_life", value="8", unit="hours",
            valid_from=datetime(2025, 1, 15, tzinfo=timezone.utc), valid_to=None, quote="8 hours of playback.",
        )
    )
    await brand_facts.create(
        BrandFactCreate(
            organisation_id=org_id, subject="Nova Buds Pro", attribute="price", value="129", unit="USD",
            valid_from=datetime(2025, 1, 15, tzinfo=timezone.utc), valid_to=datetime(2025, 6, 1, tzinfo=timezone.utc),
            quote="Intro price $129.",
        )
    )
    await brand_facts.create(
        BrandFactCreate(
            organisation_id=org_id, subject="Nova Buds Pro", attribute="price", value="149", unit="USD",
            valid_from=datetime(2025, 6, 1, tzinfo=timezone.utc), valid_to=None, quote="Now $149.",
        )
    )
    await terminology.create(
        TerminologyCreate(
            organisation_id=org_id, preferred_term="water-resistant", banned_variants=["waterproof"],
            reason="IPX4 only, not waterproof.",
        )
    )
    await claim_policies.create(
        ClaimPolicyCreate(organisation_id=org_id, pattern="clinically proven", status=ClaimPolicyStatus.BANNED)
    )


async def _create_pending_submission(api_client, headers, content=PLANTED_MISTAKE_AD):
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Ad", "content": content})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    return sub_id


# --- Gating: only pending_review may be analysed ------------------------


async def test_analyze_rejects_draft(api_client, demo_headers):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Draft", "content": "x"})
    sub_id = created.json()["id"]

    resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp.status_code == 409, resp.text


async def test_analyze_rejects_approved_and_rejected(api_client, demo_headers):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id = await _create_pending_submission(api_client, headers)

    from app.models import SubmissionStatus
    from app.repositories import submissions

    for terminal in (SubmissionStatus.APPROVED, SubmissionStatus.REJECTED, SubmissionStatus.CHANGES_REQUESTED):
        await submissions.update(sub_id, {"status": terminal}, organisation_id=org.id)
        resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
        assert resp.status_code == 409, f"{terminal}: {resp.text}"


# --- Degraded mode (no AI providers configured) -------------------------


async def test_degraded_mode_runs_rules_and_reports_ai_unavailable(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id = await _create_pending_submission(api_client, headers)

    monkeypatch.setattr(orchestrator_module, "get_llm_provider", lambda: None)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: None)

    resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["ai_available"] is False
    unavailable_checks = {u["check"] for u in report["ai_checks_unavailable"]}
    assert "claim_extraction" in unavailable_checks
    assert "tone_analysis" in unavailable_checks
    assert report["ai_checks_completed"] == []

    findings_resp = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    findings = findings_resp.json()
    assert len(findings) > 0  # rule engine still found things
    assert all(f["source"] == "rule" for f in findings)  # no fabricated LLM findings
    categories = {f["category"] for f in findings}
    assert "terminology" in categories  # "waterproof"
    assert "claim" in categories  # "clinically proven"
    assert "fact" in categories  # regex-degraded battery/price claims
    verdicts = {f["verdict"] for f in findings}
    assert "contradicted" in verdicts  # 12 hours vs 8 hours
    assert "outdated" in verdicts  # $129 vs current $149


# --- Full AI pipeline (fake providers) + caching -------------------------


async def test_full_pipeline_with_fake_providers_and_caching(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id = await _create_pending_submission(api_client, headers)

    fake_llm = FakeLLMProvider(
        responses={
            "claims": {
                "claims": [
                    {"subject": "Nova Buds Pro", "attribute": "battery_life", "value": "12", "unit": "hours", "source_quote": "12 hours"},
                ]
            },
            "findings": {
                "findings": [
                    {"category": "tone", "severity": "low", "span_text": "Clinically proven to feel great.",
                     "explanation": "Vague wellness claim with no clear audience benefit.", "suggestion": None,
                     "guideline_chunk_index": None},
                ]
            },
        }
    )
    fake_embedder = FakeEmbeddingProvider()
    monkeypatch.setattr(orchestrator_module, "get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: fake_embedder)

    resp1 = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp1.status_code == 200, resp1.text
    report1 = resp1.json()
    assert report1["ai_available"] is True
    assert set(report1["ai_checks_completed"]) >= {"claim_extraction", "retrieval", "tone_analysis"}
    assert report1["used_cache"] is False
    llm_calls_after_first = len(fake_llm.calls)
    embed_calls_after_first = len(fake_embedder.calls)
    assert llm_calls_after_first == 2  # extract_claims + flag_tone_issues
    assert embed_calls_after_first == 1  # the content's own query embedding

    findings_resp = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    findings = findings_resp.json()
    fact_findings = [f for f in findings if f["category"] == "fact" and f["source"] == "rule"]
    assert any(f["verdict"] == "contradicted" for f in fact_findings)  # battery claim vs brand fact
    tone_findings = [f for f in findings if f["source"] == "llm"]
    assert len(tone_findings) == 1
    assert tone_findings[0]["verdict"] == "needs_review"  # always hardcoded, never from the LLM

    # Re-analysing the SAME revision, SAME config -> must hit the cache:
    # no new AI calls, and findings replaced (not duplicated).
    resp2 = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp2.status_code == 200, resp2.text
    report2 = resp2.json()
    assert report2["used_cache"] is True
    assert len(fake_llm.calls) == llm_calls_after_first  # no new calls
    assert len(fake_embedder.calls) == embed_calls_after_first

    findings_resp2 = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    findings2 = findings_resp2.json()
    assert len(findings2) == len(findings)  # replaced, not duplicated
    assert {f["id"] for f in findings2} != {f["id"] for f in findings}  # genuinely new documents, not a no-op


async def test_cache_invalidated_by_prompt_version_bump(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id = await _create_pending_submission(api_client, headers, content="Simple ad with no planted mistakes.")

    fake_llm = FakeLLMProvider()
    fake_embedder = FakeEmbeddingProvider()
    monkeypatch.setattr(orchestrator_module, "get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: fake_embedder)

    first = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert first.json()["used_cache"] is False
    calls_before = len(fake_llm.calls)

    second = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert second.json()["used_cache"] is True
    assert len(fake_llm.calls) == calls_before  # confirms the cache really was live before the bump below

    # Bumping the prompt version must invalidate every cached result, even
    # with identical content and no guideline changes -- it's part of
    # config_version precisely so a prompt rewrite can force recomputation.
    from app.core.config import settings

    monkeypatch.setattr(settings, "analysis_prompt_version", "v2-rewrite")

    third = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert third.json()["used_cache"] is False
    assert len(fake_llm.calls) > calls_before


async def test_cache_invalidated_by_guideline_corpus_change(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id = await _create_pending_submission(api_client, headers, content="Simple ad with no planted mistakes.")

    fake_llm = FakeLLMProvider()
    fake_embedder = FakeEmbeddingProvider()
    monkeypatch.setattr(orchestrator_module, "get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: fake_embedder)

    first = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert first.json()["used_cache"] is False
    calls_before = len(fake_llm.calls)

    # Adding a new guideline doc changes this org's guideline-corpus
    # fingerprint, which is part of config_version -- must invalidate the
    # cache even though the submission's own content is unchanged.
    from app.models import GuidelineDocCreate, GuidelineDocStatus
    from app.repositories import guideline_docs

    await guideline_docs.create(
        GuidelineDocCreate(
            organisation_id=org.id, title="New Guidelines", filename="new.pdf", uploaded_by=_user.id,
            page_count=1, status=GuidelineDocStatus.READY,
        )
    )

    second = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert second.json()["used_cache"] is False
    assert len(fake_llm.calls) > calls_before  # AI was actually re-invoked, not skipped


async def test_malformed_llm_output_falls_back_without_crashing(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    await _seed_minimal_nova(org.id)
    sub_id = await _create_pending_submission(api_client, headers)

    # Missing the required "source_quote" field -- must fail Pydantic
    # validation and be treated as a provider failure, not crash the
    # request or silently fabricate a claim.
    fake_llm = FakeLLMProvider(responses={"claims": {"claims": [{"subject": "X", "attribute": "Y", "value": "1"}]}})
    fake_embedder = FakeEmbeddingProvider()
    monkeypatch.setattr(orchestrator_module, "get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: fake_embedder)

    resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    unavailable_checks = {u["check"] for u in report["ai_checks_unavailable"]}
    assert "claim_extraction" in unavailable_checks  # schema validation failure reported, not swallowed

    # Degraded regex fallback still ran -- the planted battery mistake is
    # still caught even though the LLM's output was rejected.
    findings_resp = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    findings = findings_resp.json()
    assert any(f["category"] == "fact" and f["verdict"] == "contradicted" for f in findings)


# --- Content length limit ------------------------------------------------


async def test_content_length_limit_enforced(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    from app.core.config import settings

    monkeypatch.setattr(settings, "analysis_max_content_chars", 10)
    sub_id = await _create_pending_submission(api_client, headers, content="This is way more than ten characters.")

    resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp.status_code == 413, resp.text


# --- Organisation isolation ----------------------------------------------


async def _other_org_headers():
    org = await organisations.create(OrganisationCreate(name="Other Org Analysis"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Other", email="other-analysis@example.com", role=UserRole.CREATOR)
    )
    return {"X-Organisation-Id": str(org.id), "X-User-Id": str(user.id)}, org, user


async def test_analyze_and_findings_cross_org_isolation(api_client, demo_headers):
    headers_a, org_a, _user_a = demo_headers
    await _seed_minimal_nova(org_a.id)
    sub_id = await _create_pending_submission(api_client, headers_a)
    await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers_a)

    headers_b, _org_b, _user_b = await _other_org_headers()
    assert (await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers_b)).status_code == 404
    assert (await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers_b)).status_code == 404

    # Org A's own findings are untouched by org B's failed cross-org attempt.
    still_there = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers_a)
    assert len(still_there.json()) > 0


async def test_cache_does_not_cross_organisation_boundaries(api_client, demo_headers, monkeypatch):
    headers_a, org_a, _user_a = demo_headers
    await _seed_minimal_nova(org_a.id)
    sub_a = await _create_pending_submission(api_client, headers_a, content="Shared identical content.")

    headers_b, org_b, user_b = await _other_org_headers()
    await _seed_minimal_nova(org_b.id)
    created_b = await api_client.post("/api/submissions", headers=headers_b, json={"title": "Ad", "content": "Shared identical content."})
    sub_b = created_b.json()["id"]
    await api_client.post(f"/api/submissions/{sub_b}/submit", headers=headers_b)

    fake_llm = FakeLLMProvider()
    fake_embedder = FakeEmbeddingProvider()
    monkeypatch.setattr(orchestrator_module, "get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr(orchestrator_module, "get_embedding_provider", lambda: fake_embedder)

    await api_client.post(f"/api/submissions/{sub_a}/analyze", headers=headers_a)
    calls_after_a = len(fake_llm.calls)
    # Org B analysing identical content must NOT be served from org A's
    # cache (which lives on org A's own revision document) -- it must run
    # its own AI calls.
    resp_b = await api_client.post(f"/api/submissions/{sub_b}/analyze", headers=headers_b)
    assert resp_b.json()["used_cache"] is False
    assert len(fake_llm.calls) > calls_after_a
