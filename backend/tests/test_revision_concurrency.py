"""Phase 4 revision-concurrency fix (app/routers/submissions.py::create_revision).

Reproduces the original defect under genuine concurrency -- not sequential
calls -- using an asyncio.Barrier so every racing request issues its HTTP
call at the same instant, then asserts every invariant the fix is supposed
to guarantee. Runs against the same isolated `clarivue_ai_test` database as
the rest of the suite (see conftest.py's `clean_db` autouse fixture);
nothing here touches real data.
"""

import asyncio

import app.core.db as db_module
from app.core.db import db as mongo_db
from app.core.db import ensure_indexes
from app.models import SubmissionStatus
from app.repositories import submissions

N_CONCURRENT = 5
N_RUNS = 10


async def _race_revise(api_client, headers, submission_id: str, n: int) -> list:
    barrier = asyncio.Barrier(n)

    async def attempt(i: int):
        await barrier.wait()  # every request fires at the same instant
        return await api_client.post(
            f"/api/submissions/{submission_id}/revise",
            headers=headers,
            json={"content": f"racing content attempt {i}"},
        )

    return await asyncio.gather(*[attempt(i) for i in range(n)])


async def _run_one_race(api_client, demo_headers, initial_status: SubmissionStatus) -> dict:
    headers, org, _user = demo_headers
    created = await api_client.post(
        "/api/submissions", headers=headers, json={"title": "Race", "content": "v1 original content"}
    )
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    if initial_status == SubmissionStatus.CHANGES_REQUESTED:
        await submissions.update(sub_id, {"status": SubmissionStatus.CHANGES_REQUESTED}, organisation_id=org.id)

    responses = await _race_revise(api_client, headers, sub_id, N_CONCURRENT)
    status_codes = [r.status_code for r in responses]

    successes = [r for r in responses if r.status_code == 201]
    conflicts = [r for r in responses if r.status_code == 409]

    history = (await api_client.get(f"/api/submissions/{sub_id}/revisions", headers=headers)).json()
    versions = [r["version"] for r in history]
    final_sub = (await api_client.get(f"/api/submissions/{sub_id}", headers=headers)).json()
    v1 = next(r for r in history if r["version"] == 1)

    assert len(successes) == 1, f"expected exactly 1 success, got {len(successes)}: {status_codes}"
    assert len(conflicts) == N_CONCURRENT - 1, f"expected {N_CONCURRENT - 1} 409s, got {len(conflicts)}: {status_codes}"
    assert len(history) == 2, f"expected exactly 2 revisions total (no orphans), got {len(history)}: {versions}"
    assert versions == [1, 2], f"unexpected/duplicate version numbers: {versions}"
    assert final_sub["current_revision"] == 2
    assert final_sub["status"] == "draft"
    assert v1["content"] == "v1 original content"  # untouched by the race

    winning_content = successes[0].json()["revision"]["content"]
    v2 = next(r for r in history if r["version"] == 2)
    assert v2["content"] == winning_content  # the stored v2 matches whichever request actually won

    return {"status_codes": status_codes}


async def test_concurrent_revise_from_pending_review_10_runs(api_client, demo_headers):
    for run in range(N_RUNS):
        result = await _run_one_race(api_client, demo_headers, SubmissionStatus.PENDING_REVIEW)
        print(f"run {run + 1}/{N_RUNS} (pending_review): {result['status_codes']}")


async def test_concurrent_revise_from_changes_requested_10_runs(api_client, demo_headers):
    for run in range(N_RUNS):
        result = await _run_one_race(api_client, demo_headers, SubmissionStatus.CHANGES_REQUESTED)
        print(f"run {run + 1}/{N_RUNS} (changes_requested): {result['status_codes']}")


async def test_unique_index_created_when_no_duplicates_exist(api_client):
    await ensure_indexes()
    # Read via the module, not a direct name import: `global` reassignment
    # inside db.py rebinds app.core.db's own namespace, which a `from ...
    # import revisions_unique_index_active` only snapshots at import time.
    assert db_module.revisions_unique_index_active is True
    info = await mongo_db["revisions"].index_information()
    assert info["uniq_submission_version"]["unique"] is True
    assert info["uniq_submission_version"]["key"] == [("submission_id", 1), ("version", 1)]


async def test_unique_index_skipped_when_duplicates_exist(api_client):
    from bson import ObjectId

    from app.core.db import find_duplicate_revision_versions

    # clean_db's per-test setup already created the unique index (0
    # duplicates existed then) -- drop it first so inserting synthetic
    # duplicates below doesn't just get rejected by that index itself; this
    # reproduces the real-world case of duplicates written *before* the
    # index ever existed.
    await mongo_db["revisions"].drop_index("uniq_submission_version")

    fake_submission_id = ObjectId()
    dup_doc = {
        "organisation_id": ObjectId(),
        "submission_id": fake_submission_id,
        "version": 1,
        "content": "x",
        "content_type": "text/plain",
        "author_id": ObjectId(),
    }
    await mongo_db["revisions"].insert_many([dict(dup_doc), dict(dup_doc)])

    dups = await find_duplicate_revision_versions()
    assert len(dups) == 1
    assert dups[0]["_id"]["submission_id"] == fake_submission_id
    assert dups[0]["_id"]["version"] == 1
    assert dups[0]["count"] == 2

    await ensure_indexes()
    assert db_module.revisions_unique_index_active is False
    info = await mongo_db["revisions"].index_information()
    assert "uniq_submission_version" not in info  # creation must be skipped, not silently succeed
