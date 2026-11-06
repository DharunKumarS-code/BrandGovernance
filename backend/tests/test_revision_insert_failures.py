"""Focused tests for the revision-insert failure-reconciliation logic in
app/routers/submissions.py::create_revision /
_reconcile_failed_revision_insert.

A connection failure while inserting the new revision does not tell us
whether MongoDB actually committed the write before the error surfaced --
the fix must check reality (by the revision's own, pre-generated _id)
rather than assume success or failure. These tests use a thin proxy around
the real `revisions`/`submissions` repository `.collection` objects to
simulate specific failures at specific call sites, while every other call
goes through to the real, isolated `clarivue_ai_test` database (see
conftest.py's `clean_db` autouse fixture) -- nothing here touches real
data.
"""

from datetime import datetime, timezone

from bson import ObjectId
from pymongo.errors import AutoReconnect

from app.repositories import revisions, submissions


class _CollectionProxy:
    """Forwards every call to `real` except names in `overrides`, which are
    async callables of the form `override(real, *args, **kwargs)`."""

    def __init__(self, real, **overrides):
        self._real = real
        self._overrides = overrides

    def __getattr__(self, name):
        if name in self._overrides:
            override = self._overrides[name]

            async def _call(*args, **kwargs):
                return await override(self._real, *args, **kwargs)

            return _call
        return getattr(self._real, name)


async def _create_and_submit(api_client, headers, content="v1 original content") -> str:
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "T", "content": content})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    return sub_id


async def _state(api_client, headers, sub_id):
    sub = (await api_client.get(f"/api/submissions/{sub_id}", headers=headers)).json()
    history = (await api_client.get(f"/api/submissions/{sub_id}/revisions", headers=headers)).json()
    return sub, history


# --- 1. DuplicateKeyError -> existence check confirms it's NOT this
# request's own document -> rollback -> 409. Uses the real unique index
# (no mocking) by pre-inserting a genuinely conflicting revision. -----------


async def test_duplicate_key_error_confirmed_not_ours_rolls_back_to_409(api_client, demo_headers, monkeypatch):
    headers, org, _user = demo_headers
    sub_id = await _create_and_submit(api_client, headers)

    # Simulate a pre-existing conflicting revision at version 2 (e.g. legacy
    # data from before this fix) with a different _id than anything this
    # request will generate -- the real unique index then raises a genuine
    # DuplicateKeyError when create_revision tries to insert its own v2.
    now = datetime.now(timezone.utc)
    await revisions.collection.insert_one(
        {
            "organisation_id": org.id,
            "submission_id": ObjectId(sub_id),
            "version": 2,
            "content": "a conflicting pre-existing revision",
            "content_type": "text/plain",
            "author_id": org.id,
            "created_at": now,
            "updated_at": now,
        }
    )

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2 mine"})
    assert resp.status_code == 409, resp.text

    sub, history = await _state(api_client, headers, sub_id)
    assert sub["status"] == "pending_review"  # rolled back to its original status
    assert sub["current_revision"] == 1  # rolled back to its original version
    versions = sorted(r["version"] for r in history)
    assert versions == [1, 2]  # the pre-existing v2 is untouched, no second v2 was added
    v2 = next(r for r in history if r["version"] == 2)
    assert v2["content"] == "a conflicting pre-existing revision"  # not overwritten


# --- 2. Connection failure AFTER the write actually committed -> existence
# check finds it -> treated as success, claimed state preserved. -----------


async def test_connection_failure_after_commit_is_treated_as_success(api_client, demo_headers, monkeypatch):
    headers, _org, _user = demo_headers
    sub_id = await _create_and_submit(api_client, headers)

    async def insert_then_drop_connection(real, doc):
        await real.insert_one(doc)  # the write actually lands server-side
        raise AutoReconnect("simulated network blip after the write committed")

    monkeypatch.setattr(revisions, "collection", _CollectionProxy(revisions.collection, insert_one=insert_then_drop_connection))

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2 content"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["revision"]["content"] == "v2 content"

    sub, history = await _state(api_client, headers, sub_id)
    assert sub["status"] == "draft"
    assert sub["current_revision"] == 2
    assert sorted(r["version"] for r in history) == [1, 2]  # exactly one new revision, no orphan/duplicate


# --- 3. Connection failure BEFORE the write landed -> confirmed absent ->
# rollback succeeds -> 500, state restored, and a retry recovers cleanly. --


async def test_connection_failure_before_commit_rolls_back_with_500(api_client, demo_headers, monkeypatch):
    headers, _org, _user = demo_headers
    sub_id = await _create_and_submit(api_client, headers)

    async def fail_without_inserting(real, doc):
        raise AutoReconnect("simulated connection drop before the write ever reached the server")

    monkeypatch.setattr(revisions, "collection", _CollectionProxy(revisions.collection, insert_one=fail_without_inserting))

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2 content"})
    assert resp.status_code == 500, resp.text
    assert "database" in resp.json()["detail"].lower()

    sub, history = await _state(api_client, headers, sub_id)
    assert sub["status"] == "pending_review"  # fully restored
    assert sub["current_revision"] == 1
    assert [r["version"] for r in history] == [1]  # no orphaned revision document

    # Recovery: once the failure clears, a plain retry must succeed and
    # must not produce a duplicate/skipped version number.
    monkeypatch.undo()
    retry = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2 content"})
    assert retry.status_code == 201, retry.text
    assert retry.json()["submission"]["current_revision"] == 2
    _, history2 = await _state(api_client, headers, sub_id)
    assert sorted(r["version"] for r in history2) == [1, 2]


# --- 4. Insert fails AND the follow-up existence check also fails ->
# outcome genuinely unknown -> 503, claimed state left untouched (NOT
# rolled back) so nothing is guessed. --------------------------------------


async def test_insert_and_existence_check_both_fail_returns_503_without_rollback(api_client, demo_headers, monkeypatch):
    headers, _org, _user = demo_headers
    sub_id = await _create_and_submit(api_client, headers)

    async def fail_without_inserting(real, doc):
        raise AutoReconnect("simulated connection drop before the write ever reached the server")

    async def fail_find_one(real, *args, **kwargs):
        raise AutoReconnect("simulated: database still unreachable for the follow-up existence check")

    monkeypatch.setattr(
        revisions,
        "collection",
        _CollectionProxy(revisions.collection, insert_one=fail_without_inserting, find_one=fail_find_one),
    )

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2 content"})
    assert resp.status_code == 503, resp.text
    assert "retry" in resp.json()["detail"].lower()

    sub, history = await _state(api_client, headers, sub_id)
    # Left exactly as Step A's claim set it -- NOT rolled back, since the
    # outcome could not be confirmed either way.
    assert sub["status"] == "draft"
    assert sub["current_revision"] == 2
    assert [r["version"] for r in history] == [1]  # no revision document was actually created


# --- 5. Insert confirmed to have failed, but the compensating rollback
# ITSELF also fails -> 503, state left claimed/unresolved rather than a
# falsely-reported successful recovery. ------------------------------------


async def test_rollback_failure_returns_503_and_does_not_claim_recovery(api_client, demo_headers, monkeypatch):
    headers, _org, _user = demo_headers
    sub_id = await _create_and_submit(api_client, headers)

    async def fail_without_inserting(real, doc):
        raise AutoReconnect("simulated connection drop before the write ever reached the server")

    async def fail_only_the_rollback_call(real, *args, **kwargs):
        filter_ = args[0]
        if "organisation_id" not in filter_:
            # This shape (3 keys: _id/status/current_revision, no
            # organisation_id) is unique to Step C's rollback call -- Step
            # A's claim always includes organisation_id/creator_id.
            raise AutoReconnect("simulated: database unreachable during rollback itself")
        return await real.find_one_and_update(*args, **kwargs)

    monkeypatch.setattr(revisions, "collection", _CollectionProxy(revisions.collection, insert_one=fail_without_inserting))
    monkeypatch.setattr(
        submissions, "collection", _CollectionProxy(submissions.collection, find_one_and_update=fail_only_the_rollback_call)
    )

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2 content"})
    assert resp.status_code == 503, resp.text
    assert "support" in resp.json()["detail"].lower() or "recovery" in resp.json()["detail"].lower()

    sub, history = await _state(api_client, headers, sub_id)
    # Left claimed (draft/next_version) -- the rollback never actually ran,
    # so nothing was falsely reported as recovered.
    assert sub["status"] == "draft"
    assert sub["current_revision"] == 2
    assert [r["version"] for r in history] == [1]  # confirmed absent -- no orphaned revision document


# --- 6. A totally unexpected (non-pymongo) exception during insert still
# goes through the same reconciliation path -> confirmed absent -> rollback
# succeeds -> 500 (not 409 -- that status is reserved for the genuine
# conflict case). -----------------------------------------------------------


async def test_unexpected_exception_during_insert_still_reconciles_and_rolls_back(api_client, demo_headers, monkeypatch):
    headers, _org, _user = demo_headers
    sub_id = await _create_and_submit(api_client, headers)

    async def raise_unexpected(real, doc):
        raise RuntimeError("completely unrelated bug, not a pymongo error at all")

    monkeypatch.setattr(revisions, "collection", _CollectionProxy(revisions.collection, insert_one=raise_unexpected))

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2 content"})
    assert resp.status_code == 500, resp.text
    assert "RuntimeError" not in resp.json()["detail"]  # no internals/stack trace leaked to the client

    sub, history = await _state(api_client, headers, sub_id)
    assert sub["status"] == "pending_review"
    assert sub["current_revision"] == 1
    assert [r["version"] for r in history] == [1]
