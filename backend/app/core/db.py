import logging

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.errors import OperationFailure

from app.core.config import settings

logger = logging.getLogger(__name__)

client = AsyncMongoClient(settings.mongodb_uri, tz_aware=True)
db = client[settings.mongodb_db_name]

# Whether the unique (submission_id, version) index on `revisions` is
# actually active. Set by _ensure_revisions_unique_index() on every
# ensure_indexes() call. The revision-concurrency fix in
# app/routers/submissions.py::create_revision does not depend on this index
# for correctness (the atomic claim in Step A already serialises concurrent
# revises on its own) -- this is a second layer of defence, and this flag
# exists so nothing ever silently assumes that layer is active when
# pre-existing duplicate data prevented it from being created.
revisions_unique_index_active: bool = False


async def ping_db() -> bool:
    await client.admin.command("ping")
    return True


# Index spec per collection: (keys, options). `keys` matches
# pymongo's create_index signature (a field name or list of (field, direction) tuples).
INDEX_SPECS: dict[str, list[tuple[object, dict]]] = {
    "users": [("organisation_id", {}), ("email", {})],
    "guideline_docs": [("organisation_id", {}), ("status", {})],
    "guideline_chunks": [
        ("organisation_id", {}),
        ([("doc_id", ASCENDING), ("chunk_index", ASCENDING)], {}),
    ],
    "brand_facts": [
        ("organisation_id", {}),
        ([("subject", ASCENDING), ("attribute", ASCENDING)], {}),
    ],
    "terminology": [("organisation_id", {})],
    "claim_policies": [("organisation_id", {}), ("status", {})],
    "assets": [("organisation_id", {}), ("status", {})],
    "submissions": [("organisation_id", {}), ("status", {})],
    "revisions": [
        ("organisation_id", {}),
        ("submission_id", {}),
        # The (submission_id, version) uniqueness itself is handled
        # separately by _ensure_revisions_unique_index() below -- it must
        # run a duplicate check before attempting to create a *unique*
        # version of this index, which a plain entry here can't do.
    ],
    "findings": [
        ("organisation_id", {}),
        ("revision_id", {}),
        ("status", {}),
    ],
    "reviews": [
        ("organisation_id", {}),
        ("submission_id", {}),
        ("revision_id", {}),
    ],
    "audit_log": [("organisation_id", {})],
}


async def find_duplicate_revision_versions() -> list[dict]:
    """Returns one entry per (submission_id, version) pair that currently
    has more than one revision document -- e.g. exactly what a revision-
    lifecycle race condition can produce. Each entry carries the offending
    submission_id, version, how many documents share it, and their ids, so
    a caller can report real duplicates rather than just a count."""
    pipeline = [
        {
            "$group": {
                "_id": {"submission_id": "$submission_id", "version": "$version"},
                "count": {"$sum": 1},
                "revision_ids": {"$push": "$_id"},
            }
        },
        {"$match": {"count": {"$gt": 1}}},
    ]
    cursor = await db["revisions"].aggregate(pipeline)
    return [doc async for doc in cursor]


async def _ensure_revisions_unique_index() -> None:
    """Creates the unique (submission_id, version) index -- the second
    layer of defence (behind the atomic claim in
    app/routers/submissions.py::create_revision) against duplicate revision
    version numbers. Must never crash startup: if duplicate data already
    exists (e.g. written before this fix), index creation is skipped and
    loudly logged instead of silently leaving the app believing this layer
    is active when it isn't -- callers/tests can check
    `revisions_unique_index_active` to know for sure."""
    global revisions_unique_index_active

    duplicates = await find_duplicate_revision_versions()
    if duplicates:
        revisions_unique_index_active = False
        logger.error(
            "Cannot create unique index on revisions(submission_id, version): "
            "%d duplicate version group(s) already exist. The index was NOT "
            "created -- duplicate-version protection is running on the "
            "atomic claim in create_revision() alone until this data is "
            "remediated. Duplicates: %s",
            len(duplicates),
            [
                {
                    "submission_id": str(d["_id"]["submission_id"]),
                    "version": d["_id"]["version"],
                    "count": d["count"],
                    "revision_ids": [str(r) for r in d["revision_ids"]],
                }
                for d in duplicates
            ],
        )
        return

    try:
        await db["revisions"].create_index(
            [("submission_id", ASCENDING), ("version", ASCENDING)],
            unique=True,
            name="uniq_submission_version",
        )
        revisions_unique_index_active = True
    except OperationFailure as exc:
        # Defensive only: a duplicate could in theory be written between the
        # check above and this call. Same rule applies -- log loudly, don't
        # crash, don't claim the index exists.
        revisions_unique_index_active = False
        logger.error(
            "Failed to create unique index on revisions(submission_id, version) "
            "despite no duplicates being found moments earlier: %s",
            exc,
        )


async def ensure_indexes() -> None:
    for collection_name, specs in INDEX_SPECS.items():
        collection = db[collection_name]
        for keys, options in specs:
            await collection.create_index(keys, **options)
    await _ensure_revisions_unique_index()
