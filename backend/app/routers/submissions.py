"""Content submission and revision management (Phase 4).

Revision lifecycle:
- draft: editing updates the current revision IN PLACE -- it hasn't been
  analysed yet, so there is nothing to preserve a history of.
- submit: draft -> pending_review. From this point the current revision is
  frozen and must never be modified again.
- editing a pending_review/changes_requested submission creates a NEW
  revision (current_revision + 1) and returns status to draft until the
  creator resubmits.
- approved/rejected submissions can never be edited (Phase 7 territory).
- a revise attempt with content identical to the current revision is
  rejected outright -- no silent no-op revisions.

Only the submission's creator may create/edit/submit/revise it. Reads
(list/get/content/revisions/compare) are open to anyone in the org, matching
how every other Phase 3 resource behaves.
"""

import difflib
import logging
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.demo_context import DemoContext, get_demo_context, get_demo_context_from_query
from app.core.storage import (
    SUBMISSIONS_DIR,
    delete_if_exists,
    sniff_image_type,
    submission_image_path,
    submission_pdf_path,
    write_bytes,
)
from app.models import (
    AuditLogCreate,
    DismissFindingInput,
    DraftContentUpdate,
    FindingStatus,
    Review,
    ReviewCreate,
    ReviewDecision,
    ReviewDecisionInput,
    Revision,
    RevisionContentInput,
    RevisionCreate,
    Submission,
    SubmissionCreate,
    SubmissionStatus,
    SubmissionTextInput,
    UserRole,
)
from app.models.common import utcnow
from app.repositories import audit_log, findings, revisions, reviews, submissions
from app.seed import SAMPLE_AD_COPY
from app.services.analysis import ContentTooLongError, analyze_submission
from app.services.pdf_processing import PdfProcessingError, extract_pages
from app.services.suggestions import (
    build_corrected_preview,
    decide_suggestion,
    get_or_generate_correction,
    get_or_generate_evidence,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/submissions", tags=["submissions"])

# Reuses the existing guideline-PDF limit -- same kind of document, same
# reasonable ceiling, no need for a separate setting.
MAX_UPLOAD_BYTES = settings.max_guideline_upload_mb * 1024 * 1024
PDF_MAGIC = b"%PDF-"
# Phase 7 Stage 3: reuses the existing asset image-size limit -- same kind
# of file (PNG/JPEG), same reasonable ceiling.
IMAGE_UPLOAD_MAX_BYTES = settings.max_asset_upload_mb * 1024 * 1024

REVISABLE_STATUSES = {SubmissionStatus.PENDING_REVIEW, SubmissionStatus.CHANGES_REQUESTED}


async def _record_audit(entry: AuditLogCreate) -> None:
    """Every audit_log write in this file goes through here, and ONLY ever
    after its corresponding business action (submission/revision/finding/
    review write) has already committed successfully -- never before, and
    never on a failed/rejected request. This wrapper exists for the
    opposite direction: if the audit write ITSELF fails (e.g. a dropped DB
    connection) after that business action already succeeded, the failure
    must not bubble up and make the endpoint report the whole request as
    failed -- the thing the client asked for already happened and must not
    be contradicted. So: log it loudly (same pattern as the reconciliation
    logging in create_revision below) and swallow it, rather than letting
    an unrelated secondary write turn a real success into a false 500."""
    try:
        await audit_log.create(entry)
    except Exception as exc:
        logger.error(
            "Audit log write failed for action=%r entity_type=%r entity_id=%s org=%s: %r -- the underlying "
            "action already committed successfully and is NOT being rolled back or reported as failed.",
            entry.action, entry.entity_type, entry.entity_id, entry.organisation_id, exc,
        )


async def _get_owned_submission(submission_id: str, context: DemoContext):
    try:
        submission = await submissions.get(submission_id, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found.")
    return submission


def _require_creator(submission, context: DemoContext) -> None:
    if submission.creator_id != context.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the submission's creator can edit it.")


# --- Phase 7: reviewer decisions (approve/reject/request changes). ---------

_REVIEW_DECISION_TO_STATUS: dict[ReviewDecision, SubmissionStatus] = {
    ReviewDecision.APPROVED: SubmissionStatus.APPROVED,
    ReviewDecision.REJECTED: SubmissionStatus.REJECTED,
    ReviewDecision.CHANGES_REQUESTED: SubmissionStatus.CHANGES_REQUESTED,
}


def _require_reviewer(context: DemoContext) -> None:
    if context.user_role not in (UserRole.REVIEWER, UserRole.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a reviewer or admin can make a review decision.")


async def _decide_submission(
    submission, context: DemoContext, *, decision: ReviewDecision, comment: str | None
) -> tuple[Submission, Review]:
    """Shared implementation for approve/reject/request-changes. Enforces
    role + non-self-review, resolves the EXACT current (frozen) revision
    being decided on, atomically transitions the submission's status (only
    ever from PENDING_REVIEW -- the only state that means "awaiting a
    decision right now"), then records a permanent Review and an audit_log
    entry. The atomic claim below is the same pattern as
    create_revision's Step A and suggestions.decide_suggestion: exactly one
    of any number of concurrent/duplicate decision requests on this same
    submission can ever match and succeed; every other one gets a 409,
    never a silently-overwritten decision."""
    _require_reviewer(context)
    if submission.creator_id == context.user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A submission's own creator cannot review it.")

    revision = await _get_current_revision(submission)
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No current revision found for this submission.")

    new_status = _REVIEW_DECISION_TO_STATUS[decision]
    claimed = await submissions.collection.find_one_and_update(
        {"_id": submission.id, "organisation_id": context.organisation_id, "status": SubmissionStatus.PENDING_REVIEW},
        {"$set": {"status": new_status, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Only a submission with status 'pending_review' can be reviewed -- it may have already been "
            "decided (by this or another reviewer) or edited since this request was made. Reload and try again.",
        )

    # The revision content itself is never touched -- only the submission's
    # status field was just updated above, via $set on a single named field.
    review = await reviews.create(
        ReviewCreate(
            organisation_id=context.organisation_id,
            submission_id=submission.id,
            revision_id=revision.id,
            reviewer_id=context.user_id,
            decision=decision,
            comment=comment,
        )
    )
    await _record_audit(
        AuditLogCreate(
            organisation_id=context.organisation_id,
            actor_id=context.user_id,
            action=f"submission_{decision.value}",
            entity_type="submission",
            entity_id=submission.id,
            details={"revision_id": str(revision.id), "revision_version": revision.version, "comment": comment},
        )
    )
    return Submission.model_validate(claimed), review


async def _get_current_revision(submission):
    found = await revisions.list(
        organisation_id=submission.organisation_id,
        filter={"submission_id": submission.id, "version": submission.current_revision},
        limit=1,
    )
    return found[0] if found else None


async def _get_owned_finding(submission, finding_id: str, context: DemoContext):
    """Org-scoped finding lookup that ALSO confirms the finding's revision
    actually belongs to this submission -- so a valid finding id from a
    different submission in the same org (which `findings.get` alone
    would happily return) can never be acted on through the wrong
    submission's URL."""
    try:
        finding = await findings.get(finding_id, organisation_id=context.organisation_id)
    except InvalidId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid id format.")
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found.")
    revision = await revisions.get(finding.revision_id, organisation_id=context.organisation_id)
    if revision is None or revision.submission_id != submission.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found.")
    return finding, revision


async def _get_revision_by_version(submission, version: int):
    found = await revisions.list(
        organisation_id=submission.organisation_id,
        filter={"submission_id": submission.id, "version": version},
        limit=1,
    )
    return found[0] if found else None


# --- Fixed sub-paths registered BEFORE "/{submission_id}..." routes, so
# "samples"/"upload" are never swallowed by the submission_id path param.


@router.get("/samples")
async def list_sample_ads(context: DemoContext = Depends(get_demo_context)) -> Any:
    # DemoContext is required only to keep this endpoint consistent with the
    # rest of the API (an org/user session must exist); the sample content
    # itself -- the real seeded Nova Electronics ad copy -- is the same
    # regardless of which org asks.
    return [{"title": title, "content": content} for title, content in SAMPLE_AD_COPY]


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_submission_pdf(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    original_filename = file.filename or ""
    if not original_filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files are accepted.")

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {settings.max_guideline_upload_mb}MB upload limit.",
        )
    if not content.startswith(PDF_MAGIC):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File does not look like a valid PDF.")

    try:
        pages = extract_pages(content)  # also rejects encrypted/too-large PDFs
    except PdfProcessingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unreadable PDF: {exc}")

    extracted_text = "\n\n".join(text.strip() for _page, text in pages if text.strip())

    submission = await submissions.create(
        SubmissionCreate(
            organisation_id=context.organisation_id,
            title=title or original_filename,
            creator_id=context.user_id,
            current_revision=1,
            status=SubmissionStatus.DRAFT,
        )
    )
    revision = await revisions.create(
        RevisionCreate(
            organisation_id=context.organisation_id,
            submission_id=submission.id,
            version=1,
            content=extracted_text,
            content_type="application/pdf",
            author_id=context.user_id,
        )
    )

    try:
        write_bytes(submission_pdf_path(revision.id), content)
    except OSError as exc:
        # Same failure-handling shape as Phase 3's guideline/asset uploads:
        # don't leave a submission+revision pointing at a file that was
        # never actually (or only partially) written.
        delete_if_exists(submission_pdf_path(revision.id))
        await revisions.delete(revision.id, organisation_id=context.organisation_id)
        await submissions.delete(submission.id, organisation_id=context.organisation_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to store uploaded file: {exc}")

    await _record_audit(
        AuditLogCreate(
            organisation_id=context.organisation_id,
            actor_id=context.user_id,
            action="submission_created",
            entity_type="submission",
            entity_id=submission.id,
            details={"revision_id": str(revision.id)},
        )
    )
    return submission.model_dump(mode="json")


# --- Phase 7 Stage 3: image-based submissions (for visual brand-consistency
# checks). Same signature-sniffing security pattern as app/routers/assets.py
# (shared helper in app/core/storage.py) -- never trusts filename or
# client-supplied Content-Type, in either direction.


@router.post("/upload-image", status_code=status.HTTP_201_CREATED)
async def upload_submission_image(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty.")
    if len(content) > IMAGE_UPLOAD_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File exceeds the {settings.max_asset_upload_mb}MB upload limit.",
        )
    sniffed = sniff_image_type(content)
    if sniffed is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PNG or JPEG images are accepted.")
    ext, content_type = sniffed

    submission = await submissions.create(
        SubmissionCreate(
            organisation_id=context.organisation_id,
            title=title or file.filename or "Untitled image submission",
            creator_id=context.user_id,
            current_revision=1,
            status=SubmissionStatus.DRAFT,
        )
    )
    # content="" -- an image-based revision has no text body; text-based
    # rule/AI checks simply find nothing to flag, and Stage 4's visual
    # checks key off image_path instead.
    revision = await revisions.create(
        RevisionCreate(
            organisation_id=context.organisation_id,
            submission_id=submission.id,
            version=1,
            content="",
            content_type=content_type,
            author_id=context.user_id,
        )
    )
    try:
        write_bytes(submission_image_path(revision.id, ext), content)
    except OSError as exc:
        delete_if_exists(submission_image_path(revision.id, ext))
        await revisions.delete(revision.id, organisation_id=context.organisation_id)
        await submissions.delete(submission.id, organisation_id=context.organisation_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to store uploaded file: {exc}")

    await revisions.update(revision.id, {"image_path": f"{revision.id}{ext}"}, organisation_id=context.organisation_id)
    await _record_audit(
        AuditLogCreate(
            organisation_id=context.organisation_id,
            actor_id=context.user_id,
            action="submission_created",
            entity_type="submission",
            entity_id=submission.id,
            details={"revision_id": str(revision.id), "has_image": True},
        )
    )
    return submission.model_dump(mode="json")


@router.get("/{submission_id}/revisions/{version}/image")
async def get_submission_revision_image(
    submission_id: str, version: int, context: DemoContext = Depends(get_demo_context_from_query)
):
    # Query-param context (not headers), like get_asset_file -- this is
    # rendered via a plain <img src=...>.
    submission = await _get_owned_submission(submission_id, context)
    revision = await _get_revision_by_version(submission, version)
    if revision is None or not revision.image_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found for this revision.")

    path = SUBMISSIONS_DIR / revision.image_path
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found for this revision.")

    with open(path, "rb") as f:
        header = f.read(16)
    sniffed = sniff_image_type(header)
    if sniffed is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Stored file is not a supported image type and cannot be served."
        )
    _ext, content_type = sniffed

    return FileResponse(
        path,
        media_type=content_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="submission-{submission_id}-v{version}{_ext}"',
        },
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_submission(payload: SubmissionTextInput, context: DemoContext = Depends(get_demo_context)) -> Any:
    submission = await submissions.create(
        SubmissionCreate(
            organisation_id=context.organisation_id,
            title=payload.title,
            creator_id=context.user_id,
            current_revision=1,
            status=SubmissionStatus.DRAFT,
        )
    )
    revision = await revisions.create(
        RevisionCreate(
            organisation_id=context.organisation_id,
            submission_id=submission.id,
            version=1,
            content=payload.content,
            content_type=payload.content_type,
            author_id=context.user_id,
        )
    )
    await _record_audit(
        AuditLogCreate(
            organisation_id=context.organisation_id,
            actor_id=context.user_id,
            action="submission_created",
            entity_type="submission",
            entity_id=submission.id,
            details={"revision_id": str(revision.id)},
        )
    )
    return submission.model_dump(mode="json")


@router.get("")
async def list_submissions(context: DemoContext = Depends(get_demo_context)) -> Any:
    items = await submissions.list(organisation_id=context.organisation_id, limit=1000)
    return [item.model_dump(mode="json") for item in items]


@router.get("/{submission_id}")
async def get_submission(submission_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    return submission.model_dump(mode="json")


@router.get("/{submission_id}/content")
async def get_submission_content(submission_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    revision = await _get_current_revision(submission)
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No current revision found for this submission.")
    return revision.model_dump(mode="json")


@router.patch("/{submission_id}/draft")
async def update_draft(
    submission_id: str, payload: DraftContentUpdate, context: DemoContext = Depends(get_demo_context)
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    _require_creator(submission, context)

    if submission.status != SubmissionStatus.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Submission is '{submission.status.value}', not draft -- only a draft's current "
            f"revision can be edited in place.",
        )
    if payload.title is None and payload.content is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields supplied to update.")

    if payload.content is not None:
        revision = await _get_current_revision(submission)
        if revision is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No current revision found for this submission.")
        await revisions.update(revision.id, {"content": payload.content}, organisation_id=context.organisation_id)

    if payload.title is not None:
        submission = await submissions.update(
            submission.id, {"title": payload.title}, organisation_id=context.organisation_id
        )
    else:
        submission = await submissions.get(submission.id, organisation_id=context.organisation_id)

    return submission.model_dump(mode="json")


@router.post("/{submission_id}/submit")
async def submit_draft(submission_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    _require_creator(submission, context)

    if submission.status != SubmissionStatus.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only a draft can be submitted (current status: '{submission.status.value}').",
        )

    is_resubmission = submission.current_revision > 1
    updated = await submissions.update(
        submission.id,
        {"status": SubmissionStatus.PENDING_REVIEW, "submitted_at": datetime.now(timezone.utc)},
        organisation_id=context.organisation_id,
    )
    await _record_audit(
        AuditLogCreate(
            organisation_id=context.organisation_id,
            actor_id=context.user_id,
            action="submission_resubmitted" if is_resubmission else "submission_submitted",
            entity_type="submission",
            entity_id=updated.id,
            details={"revision_version": updated.current_revision},
        )
    )
    return updated.model_dump(mode="json")


@router.post("/{submission_id}/revise", status_code=status.HTTP_201_CREATED)
async def create_revision(
    submission_id: str, payload: RevisionContentInput, context: DemoContext = Depends(get_demo_context)
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    _require_creator(submission, context)

    if submission.status not in REVISABLE_STATUSES:
        if submission.status == SubmissionStatus.DRAFT:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Submission is already a draft -- use PATCH .../draft to edit its current revision in place.",
            )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Submissions with status '{submission.status.value}' cannot be edited.",
        )

    current = await _get_current_revision(submission)
    if current is not None and current.content == payload.content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content is unchanged; no new revision was created.")

    next_version = submission.current_revision + 1

    # --- Step A: atomically claim the submission -----------------------
    # One find_one_and_update call, matched on the exact state we just
    # read (still revisable, still at the version we're about to
    # supersede). MongoDB guarantees a single document update is atomic,
    # so of any number of requests racing on this same (submission_id,
    # current_revision) pair, only one can match -- the moment it flips
    # current_revision forward, every other racer's filter stops matching.
    # This alone closes the race; the unique index on revisions
    # (app/core/db.py) is a second, independent layer behind it.
    claimed = await submissions.collection.find_one_and_update(
        {
            "_id": submission.id,
            "organisation_id": context.organisation_id,
            "creator_id": context.user_id,
            "status": {"$in": [SubmissionStatus.PENDING_REVIEW, SubmissionStatus.CHANGES_REQUESTED]},
            "current_revision": submission.current_revision,
        },
        {"$set": {"status": SubmissionStatus.DRAFT, "current_revision": next_version, "updated_at": utcnow()}},
        return_document=ReturnDocument.BEFORE,
    )
    if claimed is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This submission has already been revised or its state has changed. Reload and try again.",
        )

    original_status = claimed["status"]
    original_version = claimed["current_revision"]

    # --- Step B: insert the new revision ---------------------------------
    # Only the request that won Step A reaches here. The _id is generated
    # up front (rather than left to the driver) so that if insert_one raises
    # -- for ANY reason, not just DuplicateKeyError -- we can later ask "did
    # this *exact* document land?" unambiguously, instead of guessing from
    # the exception alone. A connection error here does not mean the write
    # didn't happen; the server may have committed it before the ack was
    # lost.
    revision_id = ObjectId()
    revision_doc = RevisionCreate(
        organisation_id=context.organisation_id,
        submission_id=submission.id,
        version=next_version,
        content=payload.content,
        content_type=current.content_type if current else "text/plain",
        author_id=context.user_id,
    ).model_dump()
    now = utcnow()
    revision_doc["_id"] = revision_id
    revision_doc["created_at"] = now
    revision_doc["updated_at"] = now

    try:
        await revisions.collection.insert_one(revision_doc)
        new_revision = Revision.model_validate(revision_doc)
    except Exception as insert_exc:
        new_revision = await _reconcile_failed_revision_insert(
            context=context,
            submission_id=submission.id,
            revision_id=revision_id,
            next_version=next_version,
            original_status=original_status,
            original_version=original_version,
            insert_exc=insert_exc,
        )

    updated = await submissions.get(submission.id, organisation_id=context.organisation_id)
    return {"submission": updated.model_dump(mode="json"), "revision": new_revision.model_dump(mode="json")}


async def _reconcile_failed_revision_insert(
    *,
    context: DemoContext,
    submission_id,
    revision_id,
    next_version: int,
    original_status: str,
    original_version: int,
    insert_exc: Exception,
) -> Revision:
    """Called when inserting the new revision raised ANY exception --
    DuplicateKeyError, a dropped connection (AutoReconnect /
    ServerSelectionTimeoutError / NetworkTimeout), or anything else. The
    client not getting an ack does not mean MongoDB didn't commit the
    write, so blindly rolling back could silently orphan a committed
    revision behind a reverted submission, and blindly declaring success
    could silently drop content. Resolve it from observed state instead:

    1. Check whether *this exact* revision_id exists -> if so, the insert
       actually landed; treat it as a success and keep the claimed state
       (Step A's draft/next_version) exactly as it is.
    2. Confirmed absent -> the insert genuinely never happened; it is safe
       to run the Step C compensating rollback.
    3. The existence check itself fails -> the outcome is genuinely
       unknown; do NOT guess by rolling back (that could stomp a real
       commit). Surface a 503 and leave the claimed state untouched so a
       retry or manual reconciliation can resolve it later without risking
       a duplicate version (the unique index in app/core/db.py still
       guards that even across a later retry).
    """
    try:
        existing = await revisions.get(revision_id, organisation_id=context.organisation_id)
    except Exception as check_exc:
        logger.error(
            "create_revision: insert failed for submission %s version %s (%r), and the "
            "follow-up existence check also failed (%r) -- outcome unknown, leaving the "
            "submission claimed (status=draft, current_revision=%s) rather than guessing.",
            submission_id, next_version, insert_exc, check_exc, next_version,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Could not confirm whether the revision was saved due to a temporary database "
            "issue. No data was changed; please retry shortly.",
        )

    if existing is not None:
        logger.warning(
            "create_revision: insert_one for submission %s version %s raised %r, but the "
            "revision was confirmed present server-side afterwards (ambiguous network failure "
            "around an already-committed write) -- treating this as a success.",
            submission_id, next_version, insert_exc,
        )
        return existing

    # Confirmed absent: this insert genuinely never landed. Safe to roll
    # back -- the filter below only ever matches the exact post-claim state
    # Step A produced, so it cannot clobber any later, independently
    # successful claim.
    try:
        rollback_result = await submissions.collection.find_one_and_update(
            {"_id": submission_id, "status": SubmissionStatus.DRAFT, "current_revision": next_version},
            {"$set": {"status": original_status, "current_revision": original_version, "updated_at": utcnow()}},
        )
    except Exception as rollback_exc:
        logger.error(
            "create_revision: insert failed for submission %s version %s (%r); revision "
            "confirmed absent, but the compensating rollback ITSELF failed (%r). Submission is "
            "left claimed (status=draft, current_revision=%s) with no matching revision -- "
            "requires manual reconciliation.",
            submission_id, next_version, insert_exc, rollback_exc, next_version,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The revision could not be saved and the automatic recovery step also failed. "
            "No duplicate data was created. Please contact support if this persists.",
        )

    if rollback_result is None:
        logger.error(
            "create_revision: rollback for submission %s version %s matched no document -- its "
            "claimed state (status=draft, current_revision=%s) had already changed by the time "
            "rollback ran. Original insert error: %r.",
            submission_id, next_version, next_version, insert_exc,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The revision could not be saved and its prior state could not be safely confirmed. "
            "Please refresh and check this submission's current status before retrying.",
        )

    if isinstance(insert_exc, DuplicateKeyError):
        logger.warning(
            "create_revision: duplicate key on submission %s version %s (a different revision "
            "already holds that version); confirmed absent for this request's own id, rolled "
            "back successfully to status=%s, current_revision=%s.",
            submission_id, next_version, original_status, original_version,
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A revision with this version number already exists for this submission; "
            "its state has been restored. Please try again.",
        )

    logger.error(
        "create_revision: insert failed for submission %s version %s (%r); confirmed absent, "
        "rolled back successfully to status=%s, current_revision=%s.",
        submission_id, next_version, insert_exc, original_status, original_version,
    )
    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "The revision could not be saved due to a database error. The submission has been "
        "restored to its previous state. Please try again.",
    )


@router.get("/{submission_id}/revisions")
async def list_revisions(submission_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    items = await revisions.list(
        organisation_id=context.organisation_id, filter={"submission_id": submission.id}, limit=1000
    )
    items.sort(key=lambda r: r.version)
    return [item.model_dump(mode="json") for item in items]


@router.get("/{submission_id}/revisions/{version}")
async def get_revision(submission_id: str, version: int, context: DemoContext = Depends(get_demo_context)) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    revision = await _get_revision_by_version(submission, version)
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found.")
    return revision.model_dump(mode="json")


@router.get("/{submission_id}/compare")
async def compare_revisions(
    submission_id: str,
    from_version: int = Query(...),
    to_version: int = Query(...),
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    submission = await _get_owned_submission(submission_id, context)

    old = await _get_revision_by_version(submission, from_version)
    if old is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Revision {from_version} not found.")
    new = await _get_revision_by_version(submission, to_version)
    if new is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Revision {to_version} not found.")

    diff_lines = []
    for line in difflib.ndiff(old.content.splitlines(), new.content.splitlines()):
        marker, text = line[:2], line[2:]
        if marker == "  ":
            diff_lines.append({"type": "equal", "text": text})
        elif marker == "- ":
            diff_lines.append({"type": "removed", "text": text})
        elif marker == "+ ":
            diff_lines.append({"type": "added", "text": text})
        # "? " hint lines carry no independently meaningful text; dropped.

    return {"from_version": from_version, "to_version": to_version, "diff": diff_lines}


# --- Phase 5: AI-assisted + rule-based analysis. Open to anyone in the
# org (like every other read/analysis-adjacent action here), not
# creator-restricted -- triggering analysis doesn't edit the submission
# or its content, matching how reads are already handled above.


@router.post("/{submission_id}/analyze")
async def analyze_submission_endpoint(submission_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    submission = await _get_owned_submission(submission_id, context)

    if submission.status != SubmissionStatus.PENDING_REVIEW:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only a submission with status 'pending_review' can be analysed "
            f"(current status: '{submission.status.value}'). Draft edits can still change the current "
            f"revision in place, so analysing it would be meaningless.",
        )

    revision = await _get_current_revision(submission)
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No current revision found for this submission.")

    try:
        report = await analyze_submission(submission, revision, context)
    except ContentTooLongError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc))

    await _record_audit(
        AuditLogCreate(
            organisation_id=context.organisation_id,
            actor_id=context.user_id,
            action="submission_analyzed",
            entity_type="submission",
            entity_id=submission.id,
            details={
                "revision_id": report.revision_id,
                "findings_count": report.findings_count,
                "ai_available": report.ai_available,
            },
        )
    )
    return report.model_dump(mode="json")


@router.get("/{submission_id}/findings")
async def list_submission_findings(
    submission_id: str,
    version: int | None = Query(None, description="Defaults to the submission's current revision."),
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    revision = (
        await _get_revision_by_version(submission, version) if version is not None else await _get_current_revision(submission)
    )
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revision not found.")

    items = await findings.list(
        organisation_id=context.organisation_id, filter={"revision_id": revision.id}, limit=1000
    )
    return [item.model_dump(mode="json") for item in items]


# --- Phase 6: evidence validation + AI-powered correction suggestions +
# accept/dismiss. Evidence/suggestion generation are open to anyone in the
# org (read/analysis-adjacent, like /analyze and GET .../findings above --
# they never modify the submission's content). Accept/dismiss are
# creator-restricted, matching every other action that affects what
# eventually gets applied to this creator's own content (PATCH .../draft,
# POST .../revise).


@router.get("/{submission_id}/findings/{finding_id}/evidence")
async def get_finding_evidence(
    submission_id: str,
    finding_id: str,
    refresh: bool = Query(False, description="Re-validate against current DB records instead of using the cached result."),
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    finding, _revision = await _get_owned_finding(submission, finding_id, context)
    finding = await get_or_generate_evidence(finding, organisation_id=context.organisation_id, refresh=refresh)
    return finding.evidence.model_dump(mode="json") if finding.evidence else None


@router.post("/{submission_id}/findings/{finding_id}/suggestion")
async def generate_finding_suggestion(
    submission_id: str,
    finding_id: str,
    refresh: bool = Query(False, description="Regenerate instead of returning a cached suggestion."),
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    finding, revision = await _get_owned_finding(submission, finding_id, context)
    finding = await get_or_generate_correction(finding, revision, organisation_id=context.organisation_id, refresh=refresh)
    return finding.model_dump(mode="json")


@router.get("/{submission_id}/findings/{finding_id}/suggestion")
async def get_finding_suggestion(
    submission_id: str, finding_id: str, context: DemoContext = Depends(get_demo_context)
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    finding, _revision = await _get_owned_finding(submission, finding_id, context)
    if finding.correction is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No suggestion has been generated for this finding yet.")
    return finding.correction.model_dump(mode="json")


@router.post("/{submission_id}/findings/{finding_id}/accept")
async def accept_finding_suggestion(
    submission_id: str, finding_id: str, context: DemoContext = Depends(get_demo_context)
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    _require_creator(submission, context)
    finding, revision = await _get_owned_finding(submission, finding_id, context)

    updated = await decide_suggestion(
        finding.id, organisation_id=context.organisation_id, user_id=context.user_id, decision=FindingStatus.ACCEPTED
    )
    if updated is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This finding has already been decided (current status: '{finding.status.value}').",
        )

    await _record_audit(
        AuditLogCreate(
            organisation_id=context.organisation_id,
            actor_id=context.user_id,
            action="finding_accepted",
            entity_type="finding",
            entity_id=updated.id,
            details={"submission_id": str(submission.id), "revision_id": str(updated.revision_id), "verdict": updated.verdict.value},
        )
    )

    preview_content = build_corrected_preview(revision.content, updated)
    return {
        "finding": updated.model_dump(mode="json"),
        # A ready-to-use draft, NOT an applied change -- never written to
        # any revision here. The caller must still go through the existing
        # PATCH .../draft or POST .../revise endpoints to actually apply it.
        "preview_content": preview_content,
    }


@router.post("/{submission_id}/findings/{finding_id}/dismiss")
async def dismiss_finding_suggestion(
    submission_id: str,
    finding_id: str,
    payload: DismissFindingInput | None = None,
    context: DemoContext = Depends(get_demo_context),
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    _require_creator(submission, context)
    finding, _revision = await _get_owned_finding(submission, finding_id, context)
    dismiss_reason = payload.reason if payload is not None else None

    updated = await decide_suggestion(
        finding.id,
        organisation_id=context.organisation_id,
        user_id=context.user_id,
        decision=FindingStatus.DISMISSED,
        dismiss_reason=dismiss_reason,
    )
    if updated is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This finding has already been decided (current status: '{finding.status.value}').",
        )

    await _record_audit(
        AuditLogCreate(
            organisation_id=context.organisation_id,
            actor_id=context.user_id,
            action="finding_dismissed",
            entity_type="finding",
            entity_id=updated.id,
            details={"submission_id": str(submission.id), "revision_id": str(updated.revision_id), "reason": dismiss_reason},
        )
    )

    return updated.model_dump(mode="json")


# --- Phase 7: reviewer approval/rejection/request-changes + review history.
# Role + non-self-review enforcement lives in _decide_submission above, not
# just in the frontend -- every one of these three endpoints calls it before
# touching anything. This is a SEPARATE decision from accepting/dismissing
# an individual AI correction suggestion (see the /findings/{id}/accept and
# /dismiss endpoints above): accepting a suggestion records agreement with
# one finding's proposed text; approving/rejecting/requesting-changes here
# is the reviewer's decision on the submission as a whole.


@router.post("/{submission_id}/approve")
async def approve_submission(
    submission_id: str, payload: ReviewDecisionInput | None = None, context: DemoContext = Depends(get_demo_context)
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    comment = payload.comment if payload is not None else None
    updated, review = await _decide_submission(submission, context, decision=ReviewDecision.APPROVED, comment=comment)
    return {"submission": updated.model_dump(mode="json"), "review": review.model_dump(mode="json")}


@router.post("/{submission_id}/reject")
async def reject_submission(
    submission_id: str, payload: ReviewDecisionInput, context: DemoContext = Depends(get_demo_context)
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    if not payload.comment or not payload.comment.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A comment is required when rejecting a submission.")
    updated, review = await _decide_submission(submission, context, decision=ReviewDecision.REJECTED, comment=payload.comment)
    return {"submission": updated.model_dump(mode="json"), "review": review.model_dump(mode="json")}


@router.post("/{submission_id}/request-changes")
async def request_changes(
    submission_id: str, payload: ReviewDecisionInput, context: DemoContext = Depends(get_demo_context)
) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    if not payload.comment or not payload.comment.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A comment is required when requesting changes.")
    updated, review = await _decide_submission(
        submission, context, decision=ReviewDecision.CHANGES_REQUESTED, comment=payload.comment
    )
    return {"submission": updated.model_dump(mode="json"), "review": review.model_dump(mode="json")}


@router.get("/{submission_id}/reviews")
async def list_submission_reviews(submission_id: str, context: DemoContext = Depends(get_demo_context)) -> Any:
    submission = await _get_owned_submission(submission_id, context)
    items = await reviews.list(organisation_id=context.organisation_id, filter={"submission_id": submission.id}, limit=1000)
    items.sort(key=lambda r: r.created_at)
    return [item.model_dump(mode="json") for item in items]
