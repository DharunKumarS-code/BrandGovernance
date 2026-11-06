"""Phase 8 Stage 1: analytics over existing findings/guideline data.

No new collections. Organisation-scoped throughout, same pattern as
app/routers/dashboard.py (small number of aggregations, batched
follow-up lookups for display names rather than per-row queries).
"""

from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends

from app.core.db import db
from app.core.demo_context import DemoContext, get_demo_context
from app.repositories import claim_policies, guideline_chunks, terminology

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

TOP_N = 10


async def _findings_by_category_severity(org_id: ObjectId) -> list[dict[str, Any]]:
    cursor = await db["findings"].aggregate(
        [
            {"$match": {"organisation_id": org_id}},
            {"$group": {"_id": {"category": "$category", "severity": "$severity"}, "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
    )
    return [{"category": row["_id"]["category"], "severity": row["_id"]["severity"], "count": row["count"]} async for row in cursor]


async def _top_violations(org_id: ObjectId, category: str, evidence_record_type: str) -> list[dict[str, Any]]:
    """Counts findings of `category` grouped by the rule record they cite
    (evidence_record_id), highest first. Returns raw ids + counts; callers
    attach display names via a batched follow-up lookup (never one query
    per row)."""
    cursor = await db["findings"].aggregate(
        [
            {
                "$match": {
                    "organisation_id": org_id,
                    "category": category,
                    "evidence_record_type": evidence_record_type,
                    "evidence_record_id": {"$ne": None},
                }
            },
            {"$group": {"_id": "$evidence_record_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": TOP_N},
        ]
    )
    return [{"id": row["_id"], "count": row["count"]} async for row in cursor]


async def _insufficient_evidence_count(org_id: ObjectId) -> int:
    return await db["findings"].count_documents({"organisation_id": org_id, "evidence.status": "insufficient"})


async def _unembedded_guideline_chunk_count(org_id: ObjectId) -> int:
    return await db["guideline_chunks"].count_documents({"organisation_id": org_id, "embedding": None})


@router.get("/summary")
async def analytics_summary(context: DemoContext = Depends(get_demo_context)) -> Any:
    org_id = context.organisation_id

    terminology_hits = await _top_violations(org_id, "terminology", "terminology")
    terminology_rows = await terminology.list(
        organisation_id=org_id, filter={"_id": {"$in": [h["id"] for h in terminology_hits]}}, limit=TOP_N
    )
    terminology_names = {t.id: t.preferred_term for t in terminology_rows}

    claim_hits = await _top_violations(org_id, "claim", "claim_policy")
    claim_rows = await claim_policies.list(
        organisation_id=org_id, filter={"_id": {"$in": [h["id"] for h in claim_hits]}}, limit=TOP_N
    )
    claim_names = {c.id: c.pattern for c in claim_rows}

    return {
        "findings_by_category": await _findings_by_category_severity(org_id),
        "top_terminology_violations": [
            {"terminology_id": str(h["id"]), "preferred_term": terminology_names.get(h["id"]), "count": h["count"]}
            for h in terminology_hits
        ],
        "top_claim_policy_violations": [
            {"claim_policy_id": str(h["id"]), "pattern": claim_names.get(h["id"]), "count": h["count"]}
            for h in claim_hits
        ],
        "insufficient_evidence_count": await _insufficient_evidence_count(org_id),
        "unembedded_guideline_chunks": await _unembedded_guideline_chunk_count(org_id),
    }
