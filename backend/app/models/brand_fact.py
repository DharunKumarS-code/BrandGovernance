from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.common import OrgScopedCreate, OrgScopedModel, PyObjectId


class BrandFactCreate(OrgScopedCreate):
    subject: str
    attribute: str
    value: str
    unit: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    # Phase 3 extension: source_doc_id/page/quote loosened from required to
    # optional so the admin can record a fact without yet linking it to an
    # uploaded guideline document. This is backward compatible -- every
    # existing (Phase 2 seed) record already sets all three, so nothing that
    # reads existing data changes; only new writes may omit them.
    source_doc_id: PyObjectId | None = None
    page: int | None = None
    quote: str | None = None


class BrandFact(OrgScopedModel):
    subject: str
    attribute: str
    value: str
    unit: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    source_doc_id: PyObjectId | None = None
    page: int | None = None
    quote: str | None = None


class BrandFactUpdate(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    subject: str | None = None
    attribute: str | None = None
    value: str | None = None
    unit: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_doc_id: PyObjectId | None = None
    page: int | None = None
    quote: str | None = None
