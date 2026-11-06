"""Supports the DEMO-ONLY organisation/user selector in the frontend.

See app/core/demo_context.py for the warning and rationale. These two
endpoints are unauthenticated on purpose: they only let the demo UI
discover which organisations/users exist so it can populate a selector
and then send the chosen ids back as X-Organisation-Id/X-User-Id headers
on every other request.

Phase 9 Stage 2: this is exactly the enumeration surface flagged in the
Stage 1 audit as CRITICAL for a public deploy (anyone, no credentials,
can list every org/user id and then impersonate them via the demo
headers). Gated behind settings.enable_demo_endpoints -- set
ENABLE_DEMO_ENDPOINTS=false in production.
"""

from typing import Any

from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.repositories import organisations, users

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _require_demo_enabled() -> None:
    if not settings.enable_demo_endpoints:
        # 404, not 403 -- don't even confirm this router exists in prod.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")


@router.get("/organisations")
async def list_organisations() -> Any:
    _require_demo_enabled()
    orgs = await organisations.list(limit=100)
    return [org.model_dump(mode="json") for org in orgs]


@router.get("/organisations/{organisation_id}/users")
async def list_organisation_users(organisation_id: str) -> Any:
    _require_demo_enabled()
    try:
        org = await organisations.get(organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")
    org_users = await users.list(organisation_id=org.id, limit=100)
    # exclude password_hash -- never send it to a client, demo or not.
    return [user.model_dump(mode="json", exclude={"password_hash"}) for user in org_users]
