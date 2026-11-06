from enum import StrEnum

from app.models.common import OrgScopedCreate, OrgScopedModel, PyObjectId


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


class ReviewCreate(OrgScopedCreate):
    submission_id: PyObjectId
    revision_id: PyObjectId
    reviewer_id: PyObjectId
    decision: ReviewDecision
    comment: str | None = None


class Review(OrgScopedModel):
    submission_id: PyObjectId
    revision_id: PyObjectId
    reviewer_id: PyObjectId
    decision: ReviewDecision
    comment: str | None = None
