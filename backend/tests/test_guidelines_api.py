"""Guideline PDF upload, extraction, chunking, duplicate-processing
prevention, and cross-org isolation -- exercised through the real HTTP API."""

import fitz
from bson import ObjectId

from app.models import OrganisationCreate, UserCreate, UserRole
from app.repositories import guideline_chunks, guideline_docs, organisations, users
from app.routers import guidelines as guidelines_router


def _make_pdf_bytes(pages_text: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _make_pdf_with_n_pages(n: int) -> bytes:
    doc = fitz.open()
    for i in range(n):
        page = doc.new_page()
        page.insert_text((50, 72), f"page {i + 1}", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _make_encrypted_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((50, 72), "secret content", fontsize=11)
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner123", user_pw="user123")
    doc.close()
    return data


async def test_upload_valid_pdf_extracts_and_chunks(api_client, demo_headers):
    headers, org, user = demo_headers
    pdf_bytes = _make_pdf_bytes(["Page one content about Nova Buds Pro.", "Page two content about pricing."])

    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("brand_guide.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Test Guide"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["page_count"] == 2
    assert body["filename"] == "brand_guide.pdf"  # original filename preserved as metadata
    assert "storage_filename" not in body  # no internal path/filename leaked

    doc_id = body["id"]
    chunks_resp = await api_client.get(f"/api/guidelines/{doc_id}/chunks", headers=headers)
    assert chunks_resp.status_code == 200
    chunks = chunks_resp.json()
    assert len(chunks) == 2
    assert {c["page"] for c in chunks} == {1, 2}
    assert "Nova Buds Pro" in chunks[0]["text"]
    assert chunks[0]["organisation_id"] == str(org.id)
    assert chunks[0]["embedding"] is None  # no embeddings generated in Phase 3


async def test_upload_rejects_non_pdf_extension(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 400


async def test_upload_rejects_empty_file(api_client, demo_headers):
    headers, _org, _user = demo_headers
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 400


async def test_upload_rejects_oversized_file(api_client, demo_headers, monkeypatch):
    headers, _org, _user = demo_headers
    monkeypatch.setattr(guidelines_router, "MAX_UPLOAD_BYTES", 100)
    oversized = b"%PDF-1.4\n" + b"0" * 200
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert resp.status_code == 413


async def test_upload_rejects_corrupted_pdf(api_client, demo_headers):
    headers, _org, _user = demo_headers
    # Passes the extension + magic-byte check but isn't a real PDF structure.
    fake_pdf = b"%PDF-1.4\nthis is not actually a valid pdf body"
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("corrupt.pdf", fake_pdf, "application/pdf")},
    )
    assert resp.status_code == 400


async def test_list_and_get_guideline(api_client, demo_headers):
    headers, _org, _user = demo_headers
    pdf_bytes = _make_pdf_bytes(["Just one page."])
    upload = await api_client.post(
        "/api/guidelines", headers=headers, files={"file": ("one.pdf", pdf_bytes, "application/pdf")}
    )
    doc_id = upload.json()["id"]

    listed = await api_client.get("/api/guidelines", headers=headers)
    assert listed.status_code == 200
    assert any(d["id"] == doc_id for d in listed.json())

    detail = await api_client.get(f"/api/guidelines/{doc_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == doc_id


async def test_delete_guideline_cascades_chunks(api_client, demo_headers):
    headers, org, _user = demo_headers
    pdf_bytes = _make_pdf_bytes(["Some content to chunk."])
    upload = await api_client.post(
        "/api/guidelines", headers=headers, files={"file": ("del.pdf", pdf_bytes, "application/pdf")}
    )
    doc_id = upload.json()["id"]

    chunks_before = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc_id)})
    assert len(chunks_before) >= 1

    delete_resp = await api_client.delete(f"/api/guidelines/{doc_id}", headers=headers)
    assert delete_resp.status_code == 204

    assert await guideline_docs.get(doc_id, organisation_id=org.id) is None
    chunks_after = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc_id)})
    assert len(chunks_after) == 0


async def test_reprocessing_same_doc_id_does_not_duplicate_chunks(demo_headers):
    _headers, org, user = demo_headers
    from app.models import GuidelineDocCreate, GuidelineDocStatus

    doc = await guideline_docs.create(
        GuidelineDocCreate(
            organisation_id=org.id, title="T", filename="t.pdf", uploaded_by=user.id,
            page_count=1, status=GuidelineDocStatus.PROCESSING,
        )
    )
    await guidelines_router._store_chunks(doc.id, org.id, [{"page": 1, "chunk_index": 0, "text": "hello"}])
    await guidelines_router._store_chunks(doc.id, org.id, [{"page": 1, "chunk_index": 0, "text": "hello again"}])

    chunks = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": doc.id})
    assert len(chunks) == 1
    assert chunks[0].text == "hello again"


async def test_cross_org_guideline_and_chunk_access_rejected(api_client, demo_headers):
    headers_a, org_a, _user_a = demo_headers
    org_b = await organisations.create(OrganisationCreate(name="Org B Isolation"))
    user_b = await users.create(
        UserCreate(organisation_id=org_b.id, name="B User", email="orgb@example.com", role=UserRole.ADMIN)
    )
    headers_b = {"X-Organisation-Id": str(org_b.id), "X-User-Id": str(user_b.id)}

    pdf_bytes = _make_pdf_bytes(["Org A private content."])
    upload = await api_client.post(
        "/api/guidelines", headers=headers_a, files={"file": ("a.pdf", pdf_bytes, "application/pdf")}
    )
    doc_id = upload.json()["id"]

    # Org B must not be able to read org A's document, its chunks, or delete it.
    get_resp = await api_client.get(f"/api/guidelines/{doc_id}", headers=headers_b)
    assert get_resp.status_code == 404

    chunks_resp = await api_client.get(f"/api/guidelines/{doc_id}/chunks", headers=headers_b)
    assert chunks_resp.status_code == 404

    delete_resp = await api_client.delete(f"/api/guidelines/{doc_id}", headers=headers_b)
    assert delete_resp.status_code == 404

    # The document must still exist for org A.
    still_there = await api_client.get(f"/api/guidelines/{doc_id}", headers=headers_a)
    assert still_there.status_code == 200


async def test_upload_rejects_encrypted_pdf(api_client, demo_headers):
    """Reproduced in the Phase 3 audit: PyMuPDF opens an encrypted PDF's
    container successfully even without a password and silently returns
    empty text per page, which used to produce a misleading "ready"
    document with zero chunks. It must now be rejected outright."""
    headers, org, _user = demo_headers
    encrypted = _make_encrypted_pdf_bytes()
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("secret.pdf", encrypted, "application/pdf")},
    )
    assert resp.status_code == 400, resp.text
    assert "encrypt" in resp.json()["detail"].lower() or "password" in resp.json()["detail"].lower()

    # No document record should have been created at all for a rejected upload.
    docs = await guideline_docs.list(organisation_id=org.id, filter={"filename": "secret.pdf"})
    assert docs == []


async def test_upload_accepts_exactly_50_pages(api_client, demo_headers):
    headers, _org, _user = demo_headers
    pdf_bytes = _make_pdf_with_n_pages(50)
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("fifty.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["page_count"] == 50
    assert body["status"] == "ready"


async def test_upload_rejects_51_pages(api_client, demo_headers):
    headers, org, _user = demo_headers
    pdf_bytes = _make_pdf_with_n_pages(51)
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("fiftyone.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 400, resp.text
    assert "50" in resp.json()["detail"]

    docs = await guideline_docs.list(organisation_id=org.id, filter={"filename": "fiftyone.pdf"})
    assert docs == []


async def test_upload_write_failure_leaves_no_stuck_processing_record(api_client, demo_headers, monkeypatch):
    """Reproduced directly in the Phase 3 audit: a disk failure while
    writing the PDF used to escape uncaught and leave the document
    permanently stuck at status="processing". It must now be marked
    failed, with no orphaned chunks."""
    import app.routers.guidelines as guidelines_mod

    headers, org, _user = demo_headers

    def _boom(path, content):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(guidelines_mod, "write_bytes", _boom)

    pdf_bytes = _make_pdf_bytes(["some content"])
    resp = await api_client.post(
        "/api/guidelines",
        headers=headers,
        files={"file": ("willfail.pdf", pdf_bytes, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text  # the handler still returns the (failed) document
    body = resp.json()
    assert body["status"] == "failed"

    doc_id = body["id"]
    chunks = await guideline_chunks.list(organisation_id=org.id, filter={"doc_id": ObjectId(doc_id)})
    assert chunks == []

    refetched = await guideline_docs.get(doc_id, organisation_id=org.id)
    assert refetched.status.value == "failed"
