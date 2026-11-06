from enum import StrEnum

from app.models.common import OrgScopedCreate, OrgScopedModel, PyObjectId


class GuidelineDocStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class GuidelineDocCreate(OrgScopedCreate):
    title: str
    filename: str
    uploaded_by: PyObjectId
    page_count: int
    status: GuidelineDocStatus = GuidelineDocStatus.PENDING


class GuidelineDoc(OrgScopedModel):
    title: str
    filename: str
    uploaded_by: PyObjectId
    page_count: int
    status: GuidelineDocStatus


class GuidelineChunkCreate(OrgScopedCreate):
    doc_id: PyObjectId
    page: int
    chunk_index: int
    text: str
    embedding: list[float] | None = None
    # Phase 5: which embedding model produced `embedding` -- lets the
    # backfill command tell "never embedded" apart from "embedded under a
    # since-changed model" (both need (re)embedding; a doc that already
    # matches the currently configured model does not).
    embedding_model: str | None = None


class GuidelineChunk(OrgScopedModel):
    doc_id: PyObjectId
    page: int
    chunk_index: int
    text: str
    embedding: list[float] | None = None
    embedding_model: str | None = None
