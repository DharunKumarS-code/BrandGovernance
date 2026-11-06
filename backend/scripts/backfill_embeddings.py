"""Phase 5 one-time (but safe-to-rerun) embedding backfill.

Embeds every guideline_chunks document that either has no embedding yet,
or was embedded under a different model than the one currently configured
(settings.gemini_embedding_model) -- so switching embedding models
re-embeds everything exactly once, and re-running this script after a
partial/failed run only touches what's still missing. Operates across
every organisation (seeded demo data included -- there is no special case
for it), since guideline_chunks.list(organisation_id=None, ...) returns
every org's chunks.

Usage:
    ./venv/Scripts/python.exe scripts/backfill_embeddings.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings  # noqa: E402
from app.core.db import client  # noqa: E402
from app.repositories import guideline_chunks  # noqa: E402
from app.services.ai import get_embedding_provider  # noqa: E402
from app.services.ai.errors import ProviderUnavailableError  # noqa: E402
from app.services.analysis import embed_chunks_best_effort  # noqa: E402


async def main() -> None:
    embedder = get_embedding_provider()
    if embedder is None:
        print("GEMINI_API_KEY is not configured -- nothing to backfill. Set it in backend/.env and re-run.")
        return

    try:
        await embedder.verify()
    except ProviderUnavailableError as exc:
        print(f"Gemini API key is configured but failed verification -- aborting backfill: {exc}")
        return

    all_chunks = await guideline_chunks.list(organisation_id=None, limit=1_000_000)
    pending = [c for c in all_chunks if c.embedding is None or c.embedding_model != settings.gemini_embedding_model]

    print(f"{len(all_chunks)} total chunk(s) across all organisations; {len(pending)} need embedding under model '{settings.gemini_embedding_model}'.")
    if not pending:
        print("Nothing to do -- every chunk is already embedded under the current model.")
        return

    by_org: dict = {}
    for chunk in pending:
        by_org.setdefault(chunk.organisation_id, []).append(chunk)

    total_embedded = 0
    for org_id, org_chunks in by_org.items():
        embedded = await embed_chunks_best_effort(org_chunks, embedder, org_id)
        total_embedded += embedded
        print(f"  org {org_id}: embedded {embedded}/{len(org_chunks)} chunk(s).")

    remaining = len(pending) - total_embedded
    print(f"Done. Embedded {total_embedded}/{len(pending)} chunk(s) this run.")
    if remaining:
        print(f"{remaining} chunk(s) could not be embedded (provider failures during this run) -- safe to re-run this script to retry them.")


async def run() -> None:
    try:
        await main()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(run())
