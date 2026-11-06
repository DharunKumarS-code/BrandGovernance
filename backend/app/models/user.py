from enum import StrEnum

from app.models.common import OrgScopedCreate, OrgScopedModel


class UserRole(StrEnum):
    ADMIN = "admin"
    CREATOR = "creator"
    REVIEWER = "reviewer"


class UserCreate(OrgScopedCreate):
    name: str
    email: str
    role: UserRole
    # Phase 9 Stage 2: optional so every existing/seeded user remains
    # valid with no migration. A user with no password_hash simply cannot
    # log in via /api/auth/login (and can still be used via the existing
    # demo-context headers, when require_jwt_auth is False).
    password_hash: str | None = None


class User(OrgScopedModel):
    name: str
    email: str
    role: UserRole
    password_hash: str | None = None
