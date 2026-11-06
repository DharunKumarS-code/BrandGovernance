from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.common import OrgScopedCreate, OrgScopedModel, PyObjectId


class AnalysisCache(BaseModel):
    """Phase 5 cost control (section H.5): caches the EXPENSIVE raw AI
    outputs (extracted claims, tone findings, the content's own retrieval
    embedding) for this exact frozen revision, keyed by a content hash and
    a config_version string (model names + prompt version + a guideline-
    corpus fingerprint for this org). A frozen revision's content can
    never change, so content_hash never actually needs re-checking once
    stored -- it's kept for clarity/defence-in-depth, not because it's
    expected to differ. config_version is what actually drives
    invalidation: any change to the embedding/LLM model, prompt version,
    or the org's guideline corpus produces a new config_version, so a
    stale cache is simply never matched rather than needing explicit
    eviction. Deterministic comparisons (brand facts/terminology/claim
    policy) are NEVER cached here -- they always re-run fresh against
    current data, since that data can change between analyses even when
    the revision's content cannot."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    content_hash: str
    config_version: str
    extracted_claims: list[dict[str, Any]]
    tone_findings_raw: list[dict[str, Any]]
    # Ordered so a cache hit can resolve a cached tone finding's
    # guideline_chunk_index back to a real chunk for evidence linking,
    # without re-running the (expensive) embedding+retrieval step.
    retrieved_chunk_ids: list[PyObjectId] = []
    cached_at: datetime


class RevisionCreate(OrgScopedCreate):
    submission_id: PyObjectId
    version: int
    content: str
    content_type: str
    author_id: PyObjectId
    analysis_cache: AnalysisCache | None = None
    # Phase 7 Stage 2: set unconditionally by analyze_submission() every
    # time analysis runs, AI-available or fully degraded -- unlike
    # analysis_cache (only written on a full AI-pipeline success), this is
    # the one reliable "was this exact revision ever analysed" signal, used
    # by the dashboard to find each submission's LATEST ANALYSED revision
    # (which is not necessarily its latest revision overall).
    analyzed_at: datetime | None = None
    # Phase 7 Stage 3: stored filename (under storage.py's SUBMISSIONS_DIR)
    # for an image-based submission -- None for text/PDF-text revisions.
    image_path: str | None = None


class Revision(OrgScopedModel):
    submission_id: PyObjectId
    version: int
    content: str
    content_type: str
    author_id: PyObjectId
    analysis_cache: AnalysisCache | None = None
    analyzed_at: datetime | None = None
    image_path: str | None = None
