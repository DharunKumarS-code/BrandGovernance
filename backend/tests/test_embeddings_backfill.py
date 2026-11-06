"""Tests for Phase 5 embedding generation -- automatic on guideline
upload, graceful on provider failure (section B.6), and the backfill
command's core logic (safe to rerun, skips already-current embeddings,
re-embeds on a model change, and makes no exception for the seeded Nova
Electronics guideline -- it is backfilled exactly like any other)."""

from pathlib import Path

from bson import ObjectId

import app.routers.guidelines as guidelines_router
from app.core.config import settings
from app.repositories import guideline_chunks, guideline_docs
from app.services.analysis import embed_chunks_best_effort

from tests.ai_fakes import FakeEmbeddingProvider

DEMO_PDF_PATH = Path(__file__).resolve().parent.parent / "demo-assets" / "nova_electronics_brand_guidelines.pdf"


async def _upload_demo_pdf(api_client, headers):
    pdf_bytes = DEMO_PDF_PATH.read_bytes()
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("nova_brand_guidelines.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Nova Electronics Brand & Product Guidelines"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_upload_generates_embeddings_when_provider_available(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    fake = FakeEmbeddingProvider()
    monkeypatch.setattr(guidelines_router, "get_embedding_provider", lambda: fake)

    doc = await _upload_demo_pdf(api_client, headers)
    assert doc["status"] == "ready"

    chunks = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)
    assert len(chunks) > 0
    assert all(c.embedding is not None for c in chunks)
    assert all(c.embedding_model == settings.gemini_embedding_model for c in chunks)
    assert fake.calls  # the embedder was actually invoked


async def test_upload_keeps_chunk_data_when_embedding_provider_unavailable(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    monkeypatch.setattr(guidelines_router, "get_embedding_provider", lambda: None)

    doc = await _upload_demo_pdf(api_client, headers)
    assert doc["status"] == "ready"  # upload itself must still fully succeed

    chunks = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)
    assert len(chunks) > 0
    assert all(c.embedding is None for c in chunks)  # nothing fabricated, nothing lost


async def test_upload_keeps_chunk_and_doc_data_when_embedding_api_fails(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    failing = FakeEmbeddingProvider(fail=True)
    monkeypatch.setattr(guidelines_router, "get_embedding_provider", lambda: failing)

    doc = await _upload_demo_pdf(api_client, headers)
    assert doc["status"] == "ready"  # an embedding failure must never fail the whole upload

    chunks = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)
    assert len(chunks) > 0
    assert all(c.embedding is None for c in chunks)


async def test_backfill_embeds_pending_chunks_including_the_nova_guideline(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    monkeypatch.setattr(guidelines_router, "get_embedding_provider", lambda: None)  # upload with nothing embedded yet
    doc = await _upload_demo_pdf(api_client, headers)

    all_chunks = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)
    assert all(c.embedding is None for c in all_chunks)

    fake = FakeEmbeddingProvider()
    embedded = await embed_chunks_best_effort(all_chunks, fake, org.id)
    assert embedded == len(all_chunks)

    refetched = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)
    assert all(c.embedding is not None for c in refetched)
    assert all(c.embedding_model == settings.gemini_embedding_model for c in refetched)


async def test_backfill_is_safe_to_rerun_and_skips_already_current_chunks(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    monkeypatch.setattr(guidelines_router, "get_embedding_provider", lambda: None)
    doc = await _upload_demo_pdf(api_client, headers)
    all_chunks = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)

    fake = FakeEmbeddingProvider()
    await embed_chunks_best_effort(all_chunks, fake, org.id)
    calls_after_first_run = len(fake.calls)

    # Re-running the backfill's own "what's pending" query a second time --
    # nothing should be selected, since every chunk now matches the
    # currently configured model.
    refetched = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)
    pending = [c for c in refetched if c.embedding is None or c.embedding_model != settings.gemini_embedding_model]
    assert pending == []

    embedded_second_run = await embed_chunks_best_effort(pending, fake, org.id)
    assert embedded_second_run == 0
    assert len(fake.calls) == calls_after_first_run  # no redundant API calls


async def test_backfill_regenerates_after_a_model_change(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    monkeypatch.setattr(guidelines_router, "get_embedding_provider", lambda: None)
    doc = await _upload_demo_pdf(api_client, headers)
    all_chunks = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)

    fake_old_model = FakeEmbeddingProvider()
    await embed_chunks_best_effort(all_chunks, fake_old_model, org.id)

    # Simulate a configured-model change (e.g. gemini-embedding-001 ->
    # some future model): existing chunks' stored embedding_model no
    # longer matches, so the backfill's pending-selection logic must pick
    # them up again.
    monkeypatch.setattr(settings, "gemini_embedding_model", "gemini-NEW-MODEL")
    refetched = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)
    pending = [c for c in refetched if c.embedding is None or c.embedding_model != settings.gemini_embedding_model]
    assert len(pending) == len(all_chunks)

    fake_new_model = FakeEmbeddingProvider()
    embedded = await embed_chunks_best_effort(pending, fake_new_model, org.id)
    assert embedded == len(all_chunks)

    final = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc["id"])}, limit=1000)
    assert all(c.embedding_model == "gemini-NEW-MODEL" for c in final)


async def test_backfill_covers_every_organisation_not_just_one(demo_headers):
    """guideline_chunks.list(organisation_id=None, ...), as the backfill
    script itself uses, must return chunks across ALL orgs -- confirming
    there is no org-scoping that would silently exclude anyone's data."""
    headers, org_a, _user_a = demo_headers
    from app.models import GuidelineDocCreate, GuidelineDocStatus, OrganisationCreate, UserCreate, UserRole
    from app.repositories import organisations, users

    org_b = await organisations.create(OrganisationCreate(name="Org B Backfill"))
    user_b = await users.create(
        UserCreate(organisation_id=org_b.id, name="B", email="b-backfill@example.com", role=UserRole.CREATOR)
    )

    for org_id, uploader_id in ((org_a.id, _user_a.id), (org_b.id, user_b.id)):
        doc = await guideline_docs.create(
            GuidelineDocCreate(
                organisation_id=org_id, title="T", filename="f.pdf", uploaded_by=uploader_id,
                page_count=1, status=GuidelineDocStatus.READY,
            )
        )
        from app.models import GuidelineChunkCreate

        await guideline_chunks.create(
            GuidelineChunkCreate(organisation_id=org_id, doc_id=doc.id, page=1, chunk_index=0, text="hello", embedding=None)
        )

    all_chunks = await guideline_chunks.list(organisation_id=None, limit=1_000_000)
    orgs_represented = {c.organisation_id for c in all_chunks}
    assert org_a.id in orgs_represented
    assert org_b.id in orgs_represented
