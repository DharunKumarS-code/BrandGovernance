"""Top-k guideline-chunk retrieval by embedding similarity.

Brute-force cosine similarity in plain Python over one organisation's
chunks -- a demo-scale guideline corpus (tens to low hundreds of chunks)
makes a vector database pure overkill, and this keeps the "lightweight,
free-tier-friendly" footprint the spec asks for.
"""

import math

from app.models import GuidelineChunk


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_k_chunks_by_similarity(
    query_embedding: list[float], chunks: list[GuidelineChunk], k: int
) -> list[tuple[GuidelineChunk, float]]:
    """Returns up to k (chunk, score) pairs, highest similarity first.
    Chunks with no embedding yet (not backfilled) are skipped -- they
    simply cannot participate in retrieval until embedded, rather than
    crashing or being scored arbitrarily."""
    scored = [
        (chunk, _cosine_similarity(query_embedding, chunk.embedding))
        for chunk in chunks
        if chunk.embedding is not None
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:k]
