import logging
from contextlib import asynccontextmanager

from bson.errors import InvalidId
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.db import ensure_indexes, ping_db
from app.core.middleware import MaxContentLengthMiddleware
from app.core.storage import ensure_storage_dirs
from app.routers import analytics, assets, auth, brand_facts, claim_policies, dashboard, demo, guidelines, submissions, terminology
from app.services.ai import ProviderUnavailableError, get_embedding_provider, get_llm_provider

logger = logging.getLogger(__name__)


async def _verify_ai_providers_at_startup() -> None:
    """Non-fatal by design (section F: AI being unavailable must never
    stop the app from working) -- this only logs whether the configured
    key actually authenticates, so a misconfigured/invalid key is visible
    in the logs immediately rather than only surfacing deep inside a
    user's first analysis request. Gemini covers both the LLM and
    embedding roles under one GEMINI_API_KEY, but each is verified via its
    own real endpoint (generation vs. embedding) since a key can in
    principle be valid for one and not the other (e.g. a scoped key)."""
    llm = get_llm_provider()
    if llm is None:
        logger.warning("Phase 5: GEMINI_API_KEY not configured -- analysis will run in rule-only degraded mode.")
    else:
        try:
            await llm.verify()
            logger.info("Phase 5: Gemini API key verified successfully for content generation.")
        except ProviderUnavailableError as exc:
            logger.error("Phase 5: GEMINI_API_KEY is configured but failed verification for content generation: %s", exc)

    embedder = get_embedding_provider()
    if embedder is None:
        logger.warning("Phase 5: GEMINI_API_KEY not configured -- retrieval-based analysis will be unavailable.")
    else:
        try:
            await embedder.verify()
            logger.info("Phase 5: Gemini API key verified successfully for embeddings.")
        except ProviderUnavailableError as exc:
            logger.error("Phase 5: GEMINI_API_KEY is configured but failed verification for embeddings: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_indexes()
    ensure_storage_dirs()
    await _verify_ai_providers_at_startup()
    yield


app = FastAPI(title="Clarivue AI", version="0.1.0", lifespan=lifespan)

# Middleware order matters: Starlette wraps the *last*-added middleware
# outermost, so MaxContentLengthMiddleware is added first (inner) and
# CORSMiddleware last (outer). That way a 413 from the size check still
# passes back through CORS, instead of the browser seeing a CORS failure
# in place of the actual error.
app.add_middleware(MaxContentLengthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(guidelines.router)
app.include_router(brand_facts.router)
app.include_router(terminology.router)
app.include_router(claim_policies.router)
app.include_router(assets.router)
app.include_router(submissions.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(demo.router)
app.include_router(auth.router)


@app.exception_handler(InvalidId)
async def invalid_id_handler(request: Request, exc: InvalidId) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": "Invalid id format."})


@app.get("/health")
async def health():
    db_ok = True
    db_error = None
    try:
        await ping_db()
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    return {
        "status": "ok",
        "service": "clarivue-ai-backend",
        "mongodb_connected": db_ok,
        "mongodb_error": db_error,
    }
