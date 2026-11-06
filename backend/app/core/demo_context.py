"""Organisation/user context -- demo headers (legacy) + real JWT (Phase 9).

Originally (Phase 3) this validated only the client-supplied
X-Organisation-Id/X-User-Id demo headers. Phase 9 Stage 2 adds a REAL,
verified path: when a request carries `Authorization: Bearer <jwt>`, the
organisation/user identity is derived ENTIRELY from the verified token
payload -- the X-Organisation-Id/X-User-Id headers are not even read in
that case, so a client cannot override its own authenticated identity by
also sending those headers. When no token is present, behaviour is
UNCHANGED from before (the demo headers, as long as
settings.require_jwt_auth is False) -- this keeps every existing
router/test working with zero changes, since every route already depends
on get_demo_context() by name.

settings.require_jwt_auth=True (production) removes the demo-header
fallback entirely: an unauthenticated request is rejected outright.
"""

from dataclasses import dataclass

from bson.errors import InvalidId
from fastapi import Header, HTTPException, Query, Request, status

from app.core.config import settings
from app.core.security import JWTError, decode_access_token
from app.models.common import PyObjectId
from app.models.user import UserRole
from app.repositories import organisations, users


@dataclass
class DemoContext:
    organisation_id: PyObjectId
    user_id: PyObjectId
    user_role: UserRole


async def _resolve_context(organisation_id: str | None, user_id: str | None) -> DemoContext:
    if not organisation_id or not user_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Organisation and user context are required.")

    try:
        org = await organisations.get(organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Organisation id is not a valid id.")
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found.")

    try:
        user = await users.get(user_id, organisation_id=org.id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "User id is not a valid id.")
    if user is None:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "User does not belong to the supplied organisation.",
        )

    return DemoContext(organisation_id=org.id, user_id=user.id, user_role=user.role)


async def _resolve_from_token(token: str) -> DemoContext:
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired authentication token.")
    user_id = payload.get("sub")
    org_id = payload.get("org")
    if not user_id or not org_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed authentication token.")
    # Defense in depth, same re-check as the demo-header path: the user
    # must still exist and still belong to this org RIGHT NOW, not just at
    # token-issue time (e.g. removed/moved since the token was minted).
    # _resolve_context already 404s/403s appropriately on either failure.
    return await _resolve_context(org_id, user_id)


async def get_demo_context(
    request: Request,
    x_organisation_id: str | None = Header(None, alias="X-Organisation-Id"),
    x_user_id: str | None = Header(None, alias="X-User-Id"),
) -> DemoContext:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return await _resolve_from_token(auth_header[7:].strip())
    if settings.require_jwt_auth:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    return await _resolve_context(x_organisation_id, x_user_id)


async def get_demo_context_from_query(
    organisation_id: str | None = Query(None, description="DEMO-ONLY organisation id"),
    user_id: str | None = Query(None, description="DEMO-ONLY user id"),
    token: str | None = Query(None, description="JWT access token, for requests (e.g. <img src>) that can't send an Authorization header"),
) -> DemoContext:
    """Same validation as get_demo_context, but reads query params instead
    of headers -- for cases (e.g. serving an <img src=...> file) where the
    browser cannot attach custom headers. A `token` query param is
    supported for the same reason Authorization can't be used there."""
    if token:
        return await _resolve_from_token(token)
    if settings.require_jwt_auth:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required.")
    return await _resolve_context(organisation_id, user_id)
