from typing import Any

from bson.errors import InvalidId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.core.config import settings
from app.core.demo_context import DemoContext, get_demo_context
from app.core.storage import delete_if_exists, guideline_pdf_path, write_bytes
from app.models import GuidelineChunkCreate, GuidelineDocCreate, GuidelineDocStatus
from app.repositories import guideline_chunks, guideline_docs
from app.services.ai import get_embedding_provider
from app.services.analysis import embed_chunks_best_effort
from app.services.pdf_processing import PdfProcessingError, extract_and_chunk

router = APIRouter(prefix="/api/guidelines", tags=["guidelines"])

MAX_UPLOAD_BYTES = settings.max_guideline_upload_mb * 1024 * 1024
PDF_MAGIC = b"%PDF-"


async def _store_chunks(doc_id, organisation_id, chunks: list[dict]) -> None:
    # Idempotent: clear any chunks already stored for this doc before
    # inserting, so reprocessing the same document never duplicates chunks.
    await guideline_chunks.delete_many({"doc_id": doc_id, "organisation_id": organisation_id})
    created = []
    for chunk in chunks:
        created.append(
            await guideline_chunks.create(
                GuidelineChunkCreate(
                    organisation_id=organisation_id,
                    doc_id=doc_id,
                    page=chunk["page"],
                    chunk_index=chunk["chunk_index"],
                    text=chunk["text"],
                    embedding=None,
                )
            )
        )

    # Phase 5: best-effort embedding generation. Never raises and never
    # blocks the upload on an embedding failure -- the chunks/document are
    # already safely stored above; an unreachable embedding API just means
    # these chunks stay embedding=None until the next upload attempt or a
    # run of scripts/backfill_embeddings.py picks them up.
    embedder = get_embedding_provider()
    if embedder is not None:
        await embed_chunks_best_effort(created, embedder, organisation_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_guideline(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    original_filename = file.filename or ""
    if not original_filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files are accepted.")

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {settings.max_guideline_upload_mb}MB upload limit.",
        )
    if not content.startswith(PDF_MAGIC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File does not look like a valid PDF.")

    try:
        chunks, page_count = extract_and_chunk(content)
    except PdfProcessingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unreadable PDF: {exc}")

    doc = await guideline_docs.create(
        GuidelineDocCreate(
            organisation_id=context.organisation_id,
            title=title or original_filename,
            filename=original_filename,
            uploaded_by=context.user_id,
            page_count=page_count,
            status=GuidelineDocStatus.PROCESSING,
        )
    )

    try:
        # Generated filename, never the user-supplied one -- see
        # app/core/storage.py. Writing the file lives in the SAME
        # try/except as chunk storage: a disk failure here used to escape
        # uncaught and leave the document stuck at status="processing"
        # forever (found in the Phase 3 security audit). Now any failure
        # from this point on is handled identically.
        write_bytes(guideline_pdf_path(doc.id), content)
        await _store_chunks(doc.id, context.organisation_id, chunks)
        doc = await guideline_docs.update(
            doc.id, {"status": GuidelineDocStatus.READY}, organisation_id=context.organisation_id
        )
    except Exception:
        # Don't leave a half-processed document: clear any partial chunks,
        # remove any partially-written file, and mark the record failed
        # rather than silently "ready" or stuck "processing".
        await guideline_chunks.delete_many({"doc_id": doc.id, "organisation_id": context.organisation_id})
        delete_if_exists(guideline_pdf_path(doc.id))
        doc = await guideline_docs.update(
            doc.id, {"status": GuidelineDocStatus.FAILED}, organisation_id=context.organisation_id
        )

    return doc.model_dump(mode="json")


@router.get("")
async def list_guidelines(context: DemoContext = Depends(get_demo_context)) -> Any:
    docs = await guideline_docs.list(organisation_id=context.organisation_id, limit=1000)
    return [doc.model_dump(mode="json") for doc in docs]


@router.get("/{doc_id}")
async def get_guideline(doc_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    try:
        doc = await guideline_docs.get(doc_id, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guideline document not found.")
    return doc.model_dump(mode="json")


@router.get("/{doc_id}/chunks")
async def list_guideline_chunks(doc_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    try:
        doc = await guideline_docs.get(doc_id, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guideline document not found.")

    chunks = await guideline_chunks.list(
        organisation_id=context.organisation_id, filter={"doc_id": doc.id}, limit=5000
    )
    chunks.sort(key=lambda c: (c.page, c.chunk_index))
    return [chunk.model_dump(mode="json") for chunk in chunks]


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_guideline(doc_id: str, context: DemoContext = Depends(get_demo_context)) -> None:
    try:
        doc = await guideline_docs.get(doc_id, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if doc is None:
        # Org-scoped lookup failed first, so we never touch another org's
        # file or chunks even if the id itself is valid.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guideline document not found.")

    await guideline_chunks.delete_many({"doc_id": doc.id, "organisation_id": context.organisation_id})
    delete_if_exists(guideline_pdf_path(doc.id))
    await guideline_docs.delete(doc.id, organisation_id=context.organisation_id)
