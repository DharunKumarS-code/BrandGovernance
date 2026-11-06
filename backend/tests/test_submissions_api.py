"""Content submission and revision management (Phase 4) -- exercised
through the real HTTP API."""

import fitz

from app.models import OrganisationCreate, SubmissionStatus, UserCreate, UserRole
from app.repositories import organisations, submissions, users


async def _other_org_headers():
    org = await organisations.create(OrganisationCreate(name="Other Org Submissions"))
    user = await users.create(
        UserCreate(organisation_id=org.id, name="Other", email="other-sub@example.com", role=UserRole.CREATOR)
    )
    return {"X-Organisation-Id": str(org.id), "X-User-Id": str(user.id)}


def _pdf_bytes(pages_text: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages_text:
        doc.new_page().insert_text((50, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


async def test_create_text_submission(api_client, demo_headers):
    headers, org, user = demo_headers
    resp = await api_client.post(
        "/api/submissions", headers=headers, json={"title": "My Ad", "content": "Hello world."}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "My Ad"
    assert body["status"] == "draft"
    assert body["current_revision"] == 1
    assert body["creator_id"] == str(user.id)

    content_resp = await api_client.get(f"/api/submissions/{body['id']}/content", headers=headers)
    assert content_resp.status_code == 200
    assert content_resp.json()["content"] == "Hello world."
    assert content_resp.json()["version"] == 1


async def test_draft_edit_updates_in_place_without_new_revision(api_client, demo_headers):
    headers, _org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Draft", "content": "v1"})
    sub_id = created.json()["id"]

    for new_content in ["v2", "v3"]:
        resp = await api_client.patch(f"/api/submissions/{sub_id}/draft", headers=headers, json={"content": new_content})
        assert resp.status_code == 200
        assert resp.json()["current_revision"] == 1  # still version 1, edited in place

    history = await api_client.get(f"/api/submissions/{sub_id}/revisions", headers=headers)
    assert len(history.json()) == 1
    assert history.json()[0]["content"] == "v3"


async def test_submit_draft_moves_to_pending_review(api_client, demo_headers):
    headers, _org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "T", "content": "c"})
    sub_id = created.json()["id"]

    resp = await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_review"
    assert body["submitted_at"] is not None

    # Submitting again (already pending_review) must be rejected.
    again = await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    assert again.status_code == 409


async def test_submitted_revision_is_frozen(api_client, demo_headers):
    headers, _org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "T", "content": "frozen content"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)

    # Draft-edit endpoint must refuse to touch a submitted (pending_review) submission.
    resp = await api_client.patch(f"/api/submissions/{sub_id}/draft", headers=headers, json={"content": "tampered"})
    assert resp.status_code == 409

    content = await api_client.get(f"/api/submissions/{sub_id}/content", headers=headers)
    assert content.json()["content"] == "frozen content"  # unchanged


async def test_editing_submitted_submission_creates_next_revision(api_client, demo_headers):
    headers, _org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "T", "content": "v1"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["submission"]["current_revision"] == 2
    assert body["submission"]["status"] == "draft"  # returns to draft until resubmitted
    assert body["revision"]["version"] == 2
    assert body["revision"]["content"] == "v2"

    history = await api_client.get(f"/api/submissions/{sub_id}/revisions", headers=headers)
    versions = [r["version"] for r in history.json()]
    assert versions == [1, 2]
    # v1 must still be retrievable, untouched.
    v1 = await api_client.get(f"/api/submissions/{sub_id}/revisions/1", headers=headers)
    assert v1.json()["content"] == "v1"


async def test_editing_changes_requested_submission_creates_next_revision(api_client, demo_headers):
    headers, org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "T", "content": "v1"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    # No reviewer workflow exists yet (Phase 7) -- simulate a reviewer
    # having requested changes directly via the repository.
    await submissions.update(sub_id, {"status": SubmissionStatus.CHANGES_REQUESTED}, organisation_id=org.id)

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "v2 improved"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["submission"]["status"] == "draft"
    assert resp.json()["submission"]["current_revision"] == 2


async def test_revise_rejects_unchanged_content(api_client, demo_headers):
    headers, _org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "T", "content": "same"})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)

    resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "same"})
    assert resp.status_code == 400

    history = await api_client.get(f"/api/submissions/{sub_id}/revisions", headers=headers)
    assert len(history.json()) == 1  # no duplicate revision created


async def test_approved_and_rejected_submissions_cannot_be_edited(api_client, demo_headers):
    headers, org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "T", "content": "v1"})
    sub_id = created.json()["id"]

    for terminal_status in (SubmissionStatus.APPROVED, SubmissionStatus.REJECTED):
        await submissions.update(sub_id, {"status": terminal_status}, organisation_id=org.id)

        draft_resp = await api_client.patch(f"/api/submissions/{sub_id}/draft", headers=headers, json={"content": "x"})
        assert draft_resp.status_code == 409

        revise_resp = await api_client.post(f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "x"})
        assert revise_resp.status_code == 409


async def test_revision_history_and_comparison(api_client, demo_headers):
    headers, _org, _user = demo_headers
    created = await api_client.post(
        "/api/submissions", headers=headers, json={"title": "T", "content": "line one\nline two"}
    )
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    await api_client.post(
        f"/api/submissions/{sub_id}/revise", headers=headers, json={"content": "line one\nline three\nline four"}
    )

    cmp_resp = await api_client.get(
        f"/api/submissions/{sub_id}/compare", headers=headers, params={"from_version": 1, "to_version": 2}
    )
    assert cmp_resp.status_code == 200, cmp_resp.text
    diff = cmp_resp.json()["diff"]
    types = {d["type"] for d in diff}
    assert "equal" in types
    assert "removed" in types  # "line two" removed
    assert "added" in types  # "line three"/"line four" added
    removed_texts = [d["text"] for d in diff if d["type"] == "removed"]
    added_texts = [d["text"] for d in diff if d["type"] == "added"]
    assert "line two" in removed_texts
    assert "line three" in added_texts


async def test_pdf_upload_and_extraction(api_client, demo_headers):
    headers, _org, _user = demo_headers
    pdf_bytes = _pdf_bytes(["Submission content from a PDF."])
    resp = await api_client.post(
        "/api/submissions/upload",
        headers=headers,
        files={"file": ("ad.pdf", pdf_bytes, "application/pdf")},
        data={"title": "PDF Ad"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "PDF Ad"
    assert body["status"] == "draft"

    content = await api_client.get(f"/api/submissions/{body['id']}/content", headers=headers)
    assert "Submission content from a PDF." in content.json()["content"]
    assert content.json()["content_type"] == "application/pdf"


async def test_pdf_upload_rejects_corrupted_and_non_pdf(api_client, demo_headers):
    headers, _org, _user = demo_headers

    non_pdf = await api_client.post(
        "/api/submissions/upload", headers=headers, files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert non_pdf.status_code == 400

    corrupted = await api_client.post(
        "/api/submissions/upload",
        headers=headers,
        files={"file": ("bad.pdf", b"%PDF-1.4\nnot really a pdf", "application/pdf")},
    )
    assert corrupted.status_code == 400


async def test_submission_cross_org_isolation(api_client, demo_headers):
    headers_a, _org, _user = demo_headers
    headers_b = await _other_org_headers()

    created = await api_client.post("/api/submissions", headers=headers_a, json={"title": "Private", "content": "c"})
    sub_id = created.json()["id"]

    assert (await api_client.get(f"/api/submissions/{sub_id}", headers=headers_b)).status_code == 404
    assert (await api_client.get(f"/api/submissions/{sub_id}/content", headers=headers_b)).status_code == 404
    assert (
        await api_client.patch(f"/api/submissions/{sub_id}/draft", headers=headers_b, json={"content": "x"})
    ).status_code == 404
    assert (await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers_b)).status_code == 404

    still_there = await api_client.get(f"/api/submissions/{sub_id}", headers=headers_a)
    assert still_there.status_code == 200
    assert still_there.json()["status"] == "draft"


async def test_only_creator_can_edit_submission(api_client, demo_headers):
    headers_creator, org, _creator_user = demo_headers
    other_user = await users.create(
        UserCreate(organisation_id=org.id, name="Colleague", email="colleague@example.com", role=UserRole.CREATOR)
    )
    headers_colleague = {"X-Organisation-Id": str(org.id), "X-User-Id": str(other_user.id)}

    created = await api_client.post(
        "/api/submissions", headers=headers_creator, json={"title": "Mine", "content": "c"}
    )
    sub_id = created.json()["id"]

    # Same org, different user: can read, cannot edit.
    read_resp = await api_client.get(f"/api/submissions/{sub_id}", headers=headers_colleague)
    assert read_resp.status_code == 200

    draft_resp = await api_client.patch(
        f"/api/submissions/{sub_id}/draft", headers=headers_colleague, json={"content": "hijacked"}
    )
    assert draft_resp.status_code == 403

    submit_resp = await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers_colleague)
    assert submit_resp.status_code == 403


async def test_pdf_upload_write_failure_leaves_no_orphaned_records(api_client, demo_headers, monkeypatch):
    import app.routers.submissions as submissions_router

    headers, org, _user = demo_headers

    def _boom(path, content):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(submissions_router, "write_bytes", _boom)

    pdf_bytes = _pdf_bytes(["content"])
    resp = await api_client.post(
        "/api/submissions/upload",
        headers=headers,
        files={"file": ("fail.pdf", pdf_bytes, "application/pdf")},
        data={"title": "Will Fail"},
    )
    assert resp.status_code == 500

    remaining = await submissions.list(organisation_id=org.id, filter={"title": "Will Fail"})
    assert remaining == []
