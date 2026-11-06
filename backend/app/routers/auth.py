"""Phase 9 Stage 2: real login. Issues a JWT that app/core/demo_context.py
then verifies on every subsequent request via Authorization: Bearer.

No signup endpoint -- users are provisioned the same way they always have
been (seed script / admin tooling), this only adds a way to authenticate
as one. Logout is a client-side token discard (stateless JWT, no
server-side session/blocklist in this stage -- see the final report for
why that's an explicitly named limitation, not an oversight).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.demo_context import DemoContext, get_demo_context
from app.core.security import create_access_token, verify_password
from app.repositories import users

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginInput(BaseModel):
    email: str
    password: str


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
