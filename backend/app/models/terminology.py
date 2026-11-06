from pydantic import BaseModel

from app.models.common import OrgScopedCreate, OrgScopedModel


class TerminologyCreate(OrgScopedCreate):
    preferred_term: str
    banned_variants: list[str]
    reason: str


class Terminology(OrgScopedModel):
    preferred_term: str
    banned_variants: list[str]
    reason: str


class TerminologyUpdate(BaseModel):
    preferred_term: str | None = None
    banned_variants: list[str] | None = None
    reason: str | None = None
