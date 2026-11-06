"""Shared guideline-chunk embedding helper, used by both the upload
endpoint (new chunks) and the backfill script (existing chunks), so
batching and failure handling live in exactly one place.
"""

from bson import ObjectId

from app.core.config import settings
from app.models import GuidelineChunk
from app.repositories import guideline_chunks
from app.services.ai import EmbeddingProvider, ProviderUnavailableError

# Comfortably under Gemini's per-request embedding batch limits for this
# demo's chunk sizes -- not something that needs to be exact, just small
# enough that one oversized guideline document can't blow a single request.
EMBEDDING_BATCH_SIZE = 100


async def embed_chunks_best_effort(
    chunks: list[GuidelineChunk], embedder: EmbeddingProvider, organisation_id: ObjectId
) -> int:
    """Embeds and persists `chunks` in batches. Never raises: a batch that
    fails is simply left unembedded (embedding/embedding_model stay None)
    for a later retry -- either the next upload attempt or the backfill
    command -- per section B.6 ("handle API failures without losing the
    original guideline or chunk data"). Returns how many chunks were
    successfully embedded."""
    embedded_count = 0
    for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[i : i + EMBEDDING_BATCH_SIZE]
        try:
            vectors = await embedder.embed([c.text for c in batch], input_type="document")
        except ProviderUnavailableError:
            continue
        for chunk, vector in zip(batch, vectors):
            await guideline_chunks.update(
                chunk.id,
                {"embedding": vector, "embedding_model": settings.gemini_embedding_model},
                organisation_id=organisation_id,
            )
            embedded_count += 1
    return embedded_count
