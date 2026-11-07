"""Phase 9 Stage 2: real login. Issues a JWT that app/core/demo_context.py
then verifies on every subsequent request via Authorization: Bearer.

No signup endpoint -- users are provisioned the same way they always have
been (seed script / admin tooling), this only adds a way to authenticate
as one. Logout is a client-side token discard (stateless JWT, no
server-side session/blocklist in this stage -- see the final report for
why that's an explicitly named limitation, not an oversight).
"""

import secrets
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.db import db
from app.core.demo_context import DemoContext, get_demo_context
from app.core.security import create_access_token, hash_password, verify_password
from app.models.common import utcnow
from app.repositories import users

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginInput(BaseModel):
    email: str
    password: str


class AdminProvisionInput(BaseModel):
    organisation_id: str
    user_id: str
    # Any prevents Pydantic's request-validation response from reflecting a
    # rejected password value back to the caller. Type and length are checked
    # below with a generic error response.
    password: Any


@router.post("/admin/provision", status_code=status.HTTP_204_NO_CONTENT)
async def provision_admin(
    payload: AdminProvisionInput,
    x_admin_bootstrap_secret: str | None = Header(None, alias="X-Admin-Bootstrap-Secret"),
) -> None:
    """Set the first password for one explicitly selected existing admin.

    Configure ADMIN_BOOTSTRAP_SECRET only during the setup window, then
    remove it. The conditional update is atomic and permits one winner.
    """
    expected = settings.admin_bootstrap_secret
    if not expected or not x_admin_bootstrap_secret or not secrets.compare_digest(
        x_admin_bootstrap_secret, expected
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid provisioning credentials.")

    if not isinstance(payload.password, str):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be 12 to 72 UTF-8 bytes.")
    try:
        password_bytes = payload.password.encode("utf-8")
    except UnicodeEncodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be 12 to 72 UTF-8 bytes.")
    if not 12 <= len(password_bytes) <= 72:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password must be 12 to 72 UTF-8 bytes.")

    try:
        org_id = ObjectId(payload.organisation_id)
        user_id = ObjectId(payload.user_id)
    except InvalidId:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Eligible administrator account not found.")

    password_hash = hash_password(payload.password)
    result = await db["users"].update_one(
        {
            "_id": user_id,
            "organisation_id": org_id,
            "role": "admin",
            "$or": [{"password_hash": None}, {"password_hash": {"$exists": False}}],
        },
        {"$set": {"password_hash": password_hash, "updated_at": utcnow()}},
    )
    if result.modified_count != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "Administrator is not eligible for provisioning.")


@router.post("/login")
async def login(payload: LoginInput) -> Any:
    # Email lookup across ALL organisations -- a login request has no org
    # context yet, that's exactly what the token will establish. The
    # Repository's org_scoped flag is a no-op when organisation_id=None.
    matches = await users.list(organisation_id=None, filter={"email": payload.email}, limit=1)
    user = matches[0] if matches else None

    # Same generic error whether the email doesn't exist, has no password
    # set (e.g. a demo-only seeded user), or the password is wrong -- never
    # reveal which case it was.
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    token, expires_in = create_access_token(
        user_id=str(user.id), organisation_id=str(user.organisation_id), role=user.role.value
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": {
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role.value,
            "organisation_id": str(user.organisation_id),
        },
    }


@router.post("/logout")
async def logout() -> Any:
    # Stateless JWT: nothing to invalidate server-side in this stage. The
    # client discarding the token is the actual logout action.
    return {"detail": "Logged out. Discard the access token client-side."}


@router.get("/me")
async def me(context: DemoContext = Depends(get_demo_context)) -> Any:
    """Confirms whatever credential was presented (JWT or, when allowed,
    demo headers) resolves to a real identity -- useful for the frontend
    to validate a stored token on load."""
    user = await users.get(context.user_id, organisation_id=context.organisation_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "organisation_id": str(user.organisation_id),
    }
