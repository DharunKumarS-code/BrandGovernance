"""Phase 7 Stage 2: a real, database-driven dashboard.

Every number below comes from an actual MongoDB query/aggregation,
organisation-scoped exactly like every other endpoint in this app. No
value is hardcoded or demo-only.

Query strategy (see the final report for the full rationale): rather than
one query per card, this uses a small, fixed number of efficient queries/
aggregations -- one for submission-status counts, one to find each
submission's LATEST ANALYSED revision, one $facet aggregation for open
findings on exactly those revisions, a couple of cheap count_documents
calls for review stats, and one capped, sorted query for recent activity.
Nothing here loads a full collection into application memory; aggregations
return only grouped counts/ids, and the activity query is limited to 15
documents.
"""

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends

from app.core.db import db
from app.core.demo_context import DemoContext, get_demo_context
from app.models import FindingStatus, SubmissionStatus
from app.repositories import assets, brand_facts, claim_policies, guideline_docs, reviews, terminology

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

RECENT_ACTIVITY_LIMIT = 15


async def _status_counts(org_id: ObjectId) -> dict[str, int]:
    counts = {s.value: 0 for s in SubmissionStatus}
    cursor = await db["submissions"].aggregate(
        [
            {"$match": {"organisation_id": org_id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
    )
    async for row in cursor:
        counts[row["_id"]] = row["count"]
    return counts


async def _latest_analysed_revision_ids(org_id: ObjectId) -> list[ObjectId]:
    """One revision id per submission: the highest-version revision that
    was ever actually analysed (Revision.analyzed_at is not None) --
    NEVER assumed to be the submission's current/latest revision overall.
    A submission with no analysed revision at all contributes nothing
    here, per spec."""
    cursor = await db["revisions"].aggregate(
        [
            {"$match": {"organisation_id": org_id, "analyzed_at": {"$ne": None}}},
            {"$sort": {"submission_id": 1, "version": -1}},
            {"$group": {"_id": "$submission_id", "revision_id": {"$first": "$_id"}}},
        ]
    )
    return [row["revision_id"] async for row in cursor]


async def _open_findings_facet(org_id: ObjectId, latest_revision_ids: list[ObjectId]) -> dict[str, Any]:
    """One aggregation, one round-trip: open-finding severity breakdown AND
    the count of distinct revisions (== distinct submissions, since each
    submission contributes at most one id to latest_revision_ids) that
    have at least one open finding -- both scoped to ONLY the latest
    analysed revisions, and both ignoring dismissed/accepted findings."""
    severity_breakdown = {"high": 0, "medium": 0, "low": 0}
    if not latest_revision_ids:
        return {"open_total": 0, "by_severity": severity_breakdown, "submissions_with_open_findings": 0}

    cursor = await db["findings"].aggregate(
        [
            {
                "$match": {
                    "organisation_id": org_id,
                    "revision_id": {"$in": latest_revision_ids},
                    "status": FindingStatus.OPEN.value,
                }
            },
            {
                "$facet": {
                    "by_severity": [{"$group": {"_id": "$severity", "count": {"$sum": 1}}}],
                    "by_revision": [{"$group": {"_id": "$revision_id"}}],
                }
            },
        ]
    )
    [facet_result] = [row async for row in cursor] or [{"by_severity": [], "by_revision": []}]

    open_total = 0
    for row in facet_result["by_severity"]:
        severity_breakdown[row["_id"]] = row["count"]
        open_total += row["count"]

    return {
        "open_total": open_total,
        "by_severity": severity_breakdown,
        "submissions_with_open_findings": len(facet_result["by_revision"]),
    }


async def _recent_activity(org_id: ObjectId) -> list[dict[str, Any]]:
    cursor = db["audit_log"].find({"organisation_id": org_id}).sort("created_at", -1).limit(RECENT_ACTIVITY_LIMIT)
    entries = [doc async for doc in cursor]
    if not entries:
        return []

    # Batched into one query, same as the submission-title lookup below --
    # was previously one users.get() call PER DISTINCT ACTOR (up to 15),
    # an unbounded-with-activity-volume round-trip count found during the
    # Phase 7 Stage 2 efficiency check and fixed here.
    actor_ids = {e["actor_id"] for e in entries if e.get("actor_id")}
    actor_names: dict[ObjectId, str] = {}
    if actor_ids:
        actor_cursor = db["users"].find({"_id": {"$in": list(actor_ids)}, "organisation_id": org_id}, {"name": 1})
        async for row in actor_cursor:
            actor_names[row["_id"]] = row["name"]

    def _submission_id_for(entry: dict) -> ObjectId | None:
        if entry.get("entity_type") == "submission":
            return entry.get("entity_id")
        raw = (entry.get("details") or {}).get("submission_id")
        if raw and ObjectId.is_valid(raw):
            return ObjectId(raw)
        return None

    submission_ids = {sid for e in entries if (sid := _submission_id_for(e)) is not None}
    submission_titles: dict[ObjectId, str] = {}
    if submission_ids:
        title_cursor = db["submissions"].find(
            {"_id": {"$in": list(submission_ids)}, "organisation_id": org_id}, {"title": 1}
        )
        async for row in title_cursor:
            submission_titles[row["_id"]] = row["title"]

    activity = []
    for e in entries:
        sid = _submission_id_for(e)
        activity.append(
            {
                "id": str(e["_id"]),
                "action": e["action"],
                # Gracefully degrades to None rather than erroring when the
                # actor/submission no longer exists -- never fabricated.
                "actor_name": actor_names.get(e.get("actor_id")),
                "submission_id": str(sid) if sid else None,
                "submission_title": submission_titles.get(sid) if sid else None,
                "created_at": e["created_at"].isoformat(),
            }
        )
    return activity


@router.get("/summary")
async def summary(context: DemoContext = Depends(get_demo_context)) -> Any:
    org_id = context.organisation_id

    status_counts = await _status_counts(org_id)
    total_submissions = sum(status_counts.values())

    latest_revision_ids = await _latest_analysed_revision_ids(org_id)
    issues = await _open_findings_facet(org_id, latest_revision_ids)

    # Review statistics are DELIBERATELY kept separate from submission
    # status counts -- "completed reviews" counts recorded decisions in the
    # `reviews` collection (every decision ever made, including a
    # changes_requested one later superseded by an approval), never
    # "submissions currently approved/rejected", which is a different
    # number reported alongside it.
    completed_reviews = await reviews.count(organisation_id=org_id)

    return {
        # Unchanged Phase 1-4 governance counts.
        "guideline_docs": await guideline_docs.count(organisation_id=org_id),
        "brand_facts": await brand_facts.count(organisation_id=org_id),
        "terminology": await terminology.count(organisation_id=org_id),
        "claim_policies": await claim_policies.count(organisation_id=org_id),
        "assets": await assets.count(organisation_id=org_id),
        "submissions": {
            "total": total_submissions,
            "draft": status_counts[SubmissionStatus.DRAFT.value],
            "pending_review": status_counts[SubmissionStatus.PENDING_REVIEW.value],
            "changes_requested": status_counts[SubmissionStatus.CHANGES_REQUESTED.value],
            "approved": status_counts[SubmissionStatus.APPROVED.value],
            "rejected": status_counts[SubmissionStatus.REJECTED.value],
            "with_ai_findings": issues["submissions_with_open_findings"],
        },
        "issues": {
            "open_total": issues["open_total"],
            "by_severity": issues["by_severity"],
        },
        "reviews": {
            "pending": status_counts[SubmissionStatus.PENDING_REVIEW.value],
            "completed": completed_reviews,
            "currently_approved": status_counts[SubmissionStatus.APPROVED.value],
            "currently_rejected": status_counts[SubmissionStatus.REJECTED.value],
        },
        "recent_activity": await _recent_activity(org_id),
    }
