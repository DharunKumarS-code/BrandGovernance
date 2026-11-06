from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel

from app.models.common import OrgScopedCreate, OrgScopedModel, PyObjectId


class SubmissionStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"


class SubmissionCreate(OrgScopedCreate):
    title: str
    creator_id: PyObjectId
    current_revision: int = 0
    status: SubmissionStatus = SubmissionStatus.DRAFT
    # Phase 4 addition: set when a draft is first submitted for review.
    # Optional/nullable so it's backward compatible with every existing
    # (Phase 2/3 seed) record, which simply has no value for it.
    submitted_at: datetime | None = None


class Submission(OrgScopedModel):
    title: str
    creator_id: PyObjectId
    current_revision: int
    status: SubmissionStatus
    submitted_at: datetime | None = None


# --- Phase 4: plain request-body shapes for the submissions API. These
# carry no PyObjectId fields, so (unlike *Create/*Update above) they're safe
# to use directly as FastAPI route parameter types -- see the docstring in
# app/routers/_crud.py for why that distinction matters.


class SubmissionTextInput(BaseModel):
    title: str
    content: str
    content_type: str = "text/plain"


class DraftContentUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class RevisionContentInput(BaseModel):
    content: str


# --- Phase 6: request body for dismissing a finding/suggestion. ------------


class DismissFindingInput(BaseModel):
    reason: str | None = None


# --- Phase 7: request body for a reviewer decision (approve/reject/request
# changes). `comment` is optional here at the schema level -- approve allows
# an empty comment, while reject/request-changes enforce a non-empty one in
# the route handler itself (app/routers/submissions.py), since that's a
# business rule specific to those two decisions, not a shape difference.


class ReviewDecisionInput(BaseModel):
    comment: str | None = None
