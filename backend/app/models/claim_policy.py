from enum import StrEnum

from pydantic import BaseModel

from app.models.common import OrgScopedCreate, OrgScopedModel


class ClaimPolicyStatus(StrEnum):
    APPROVED = "approved"
    NEEDS_EVIDENCE = "needs_evidence"
    BANNED = "banned"


class ClaimPolicyCreate(OrgScopedCreate):
    pattern: str
    status: ClaimPolicyStatus
    required_disclaimer: str | None = None


class ClaimPolicy(OrgScopedModel):
    pattern: str
    status: ClaimPolicyStatus
    required_disclaimer: str | None = None


class ClaimPolicyUpdate(BaseModel):
    pattern: str | None = None
    status: ClaimPolicyStatus | None = None
    required_disclaimer: str | None = None
