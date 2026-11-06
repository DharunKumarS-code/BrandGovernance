import asyncio
import os
import shutil
import tempfile

# Point every app import below at an isolated test database AND an isolated
# storage directory on disk, so tests never touch real/dev data or files.
os.environ["MONGODB_DB_NAME"] = "clarivue_ai_test"
_TEST_STORAGE_ROOT = tempfile.mkdtemp(prefix="clarivue_test_storage_")
os.environ["STORAGE_ROOT"] = _TEST_STORAGE_ROOT

# Phase 5: force the AI provider off for the automated suite, regardless of
# whatever is in backend/.env on the machine running the tests. Without
# this, a real GEMINI_API_KEY in .env makes this "offline" suite issue real
# network calls to Gemini (cost, flakiness, and in at least one case --
# test_guidelines_api.py::test_upload_valid_pdf_extracts_and_chunks -- a
# wrong assertion, since that test predates Phase 5's auto-embed-on-upload
# and expects embedding=None). Env vars override backend/.env in
# pydantic-settings, and this must run before app.core.config's
# module-level `settings = Settings()` is first evaluated -- i.e. before
# anything below imports app.main or app.core.config, directly or
# transitively. Does not touch the real key or .env in any way.
os.environ["GEMINI_API_KEY"] = ""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import db, ensure_indexes
from app.core.storage import ensure_storage_dirs
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_storage():
    yield
    shutil.rmtree(_TEST_STORAGE_ROOT, ignore_errors=True)


@pytest.fixture
async def api_client():
    ensure_storage_dirs()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(scope="session")
def event_loop():
    # AsyncMongoClient binds to the event loop active on its first operation
    # and refuses to be reused from a different one, so every test in this
    # session must share a single loop rather than pytest-asyncio's default
    # per-function loop.
    #
    # Investigated 2026-11-05: setting `asyncio_default_fixture_loop_scope =
    # session` in pytest.ini (the officially suggested alternative) only
    # changes the loop scope for async *fixtures*, not for test functions
    # themselves in pytest-asyncio 0.24 -- confirmed by trying it, which
    # reintroduced the "different event loop" RuntimeError on every test.
    # Getting test functions onto a shared loop without this override would
    # require tagging every test with @pytest.mark.asyncio(loop_scope=...)
    # or a pytest_collection_modifyitems hook -- more moving parts for a
    # cosmetic deprecation warning. Left as-is; the warning is harmless.
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def clean_db():
    await ensure_indexes()
    yield
    for name in await db.list_collection_names():
        await db[name].delete_many({})


@pytest.fixture
async def demo_headers():
    """Creates a throwaway organisation + user and returns the demo-context
    headers for it, matching what the real frontend selector would send."""
    from app.models import OrganisationCreate, UserCreate, UserRole
    from app.repositories import organisations, users

    org = await organisations.create(OrganisationCreate(name="API Test Org"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="API Tester", email="api-tester@example.com", role=UserRole.ADMIN)
    )
    return {"X-Organisation-Id": str(org.id), "X-User-Id": str(user.id)}, org, user
