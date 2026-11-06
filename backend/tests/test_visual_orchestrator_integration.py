"""Phase 7 Stage 3, Stage 4: orchestrator + evidence integration for visual
checks -- focused tests via the real HTTP API. No real Gemini calls."""

import cv2
import numpy as np

from app.models import AssetCreate, AssetStatus, AssetType, FindingCategory


def _logo_array(fill: int = 60) -> np.ndarray:
    arr = np.full((40, 40), fill, dtype=np.uint8)
    arr[10:30, 10:30] = 255 - fill
    return arr


def _encode(arr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", arr)
    assert ok
    return buf.tobytes()


def _embed(logo: np.ndarray, canvas: int = 160, pos=(60, 70), bg: int = 128) -> bytes:
    out = np.full((canvas, canvas), bg, dtype=np.uint8)
    h, w = logo.shape
    y, x = pos
    out[y : y + h, x : x + w] = logo
    return _encode(out)


async def _submit_image(api_client, headers, image_bytes: bytes, title="Visual Ad"):
    created = await api_client.post(
        "/api/submissions/upload-image", headers=headers, files={"file": ("ad.png", image_bytes, "image/png")}, data={"title": title}
    )
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    return sub_id


async def test_deprecated_logo_in_image_produces_visual_finding_with_valid_evidence(api_client, demo_headers):
    headers, org, _user = demo_headers
    logo_resp = await api_client.post(
        "/api/assets/upload", headers=headers, files={"file": ("old.png", _encode(_logo_array()), "image/png")},
        data={"name": "Old Logo", "status": "deprecated"},
    )
    assert logo_resp.status_code == 201, logo_resp.text

    sub_id = await _submit_image(api_client, headers, _embed(_logo_array()))
    analyze_resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert analyze_resp.status_code == 200, analyze_resp.text

    findings_resp = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    visual = [f for f in findings_resp.json() if f["category"] == "visual"]
    assert len(visual) == 1
    assert visual[0]["verdict"] == "contradicted"
    assert visual[0]["evidence_record_type"] == "asset"

    evidence_resp = await api_client.get(f"/api/submissions/{sub_id}/findings/{visual[0]['id']}/evidence", headers=headers)
    assert evidence_resp.status_code == 200
    assert evidence_resp.json()["status"] == "supported"


async def test_reanalysis_does_not_duplicate_visual_findings(api_client, demo_headers):
    headers, org, _user = demo_headers
    await api_client.post(
        "/api/assets/upload", headers=headers, files={"file": ("old.png", _encode(_logo_array()), "image/png")},
        data={"name": "Old Logo", "status": "deprecated"},
    )
    sub_id = await _submit_image(api_client, headers, _embed(_logo_array()))

    first = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    second = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["findings_count"] == second.json()["findings_count"]

    findings_resp = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    assert len(findings_resp.json()) == first.json()["findings_count"]  # no accumulation


async def test_text_submission_unaffected_no_visual_findings(api_client, demo_headers):
    headers, org, _user = demo_headers
    created = await api_client.post("/api/submissions", headers=headers, json={"title": "Text Ad", "content": "Plain ad copy."})
    sub_id = created.json()["id"]
    await api_client.post(f"/api/submissions/{sub_id}/submit", headers=headers)
    resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp.status_code == 200

    findings_resp = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    assert all(f["category"] != "visual" for f in findings_resp.json())


async def test_visual_finding_can_generate_correction_suggestion(monkeypatch):
    """Task 2: a category=VISUAL finding goes through the exact same
    get_or_generate_correction() as text findings -- proven here with a
    mocked LLM (no real Gemini call)."""
    from bson import ObjectId

    import app.services.suggestions as suggestions_module
    from app.models import FindingCreate, FindingSeverity, FindingSource, OrganisationCreate, RevisionCreate, UserCreate, UserRole, Verdict
    from app.repositories import assets as assets_repo, findings, organisations, revisions, users
    from app.services.suggestions import get_or_generate_correction
    from tests.ai_fakes import FakeLLMProvider

    org = await organisations.create(OrganisationCreate(name="Visual Suggestion Org"))
    user = await users.create(UserCreate(organisation_id=org.id, name="Tester", email="visual-suggestion@example.com", role=UserRole.ADMIN))
    asset = await assets_repo.create(
        AssetCreate(organisation_id=org.id, type=AssetType.LOGO, name="Old Logo", status=AssetStatus.DEPRECATED, file_path=None)
    )
    revision = await revisions.create(
        RevisionCreate(organisation_id=org.id, submission_id=ObjectId(), version=1, content="", content_type="image/png", author_id=user.id)
    )
    finding = await findings.create(
        FindingCreate(
            organisation_id=org.id, revision_id=revision.id, category=FindingCategory.VISUAL, severity=FindingSeverity.HIGH,
            span_text="Logo region matching 'Old Logo' (confidence 92%)",
            explanation="Matches the deprecated logo 'Old Logo'.", verdict=Verdict.CONTRADICTED,
            evidence_record_type="asset", evidence_record_id=asset.id, source=FindingSource.VISION,
        )
    )

    fake_llm = FakeLLMProvider(
        responses={"corrected_span": {"corrected_span": None, "rationale": "Replace with the current approved logo.", "requires_human_review": True}}
    )
    monkeypatch.setattr(suggestions_module, "get_llm_provider", lambda: fake_llm)

    updated = await get_or_generate_correction(finding, revision, organisation_id=org.id)
    assert len(fake_llm.calls) == 1  # real suggestion generation attempted, mocked -- not skipped
    assert updated.correction is not None
    assert updated.correction.source == FindingSource.LLM
    assert updated.evidence.status.value == "supported"


async def test_missing_logo_file_on_disk_handled_safely(api_client, demo_headers):
    """A logo Asset record with a file_path pointing at nothing on disk
    (e.g. manually tampered/corrupted) must not crash analysis."""
    headers, org, _user = demo_headers
    from app.repositories import assets as assets_repo

    asset = await assets_repo.create(
        AssetCreate(organisation_id=org.id, type=AssetType.LOGO, name="Ghost Logo", status=AssetStatus.DEPRECATED, file_path="does-not-exist.png")
    )
    assert asset.file_path == "does-not-exist.png"

    sub_id = await _submit_image(api_client, headers, _embed(_logo_array()))
    resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert resp.status_code == 200  # no crash


async def test_low_contrast_image_produces_accessibility_finding_needs_review(api_client, demo_headers):
    """Phase 8 Stage 4 wiring: an accessibility finding reaches the
    existing findings/evidence pipeline unchanged -- evidence has no
    asset to cite, so it correctly falls into the pre-existing generic
    'no specific evidence record, human review' branch in evidence.py."""
    headers, org, _user = demo_headers
    low_contrast = np.zeros((40, 40, 3), dtype=np.uint8)
    low_contrast[:20, :] = [150, 150, 150]
    low_contrast[20:, :] = [120, 120, 120]
    image_bytes = _encode(low_contrast)

    sub_id = await _submit_image(api_client, headers, image_bytes)
    analyze_resp = await api_client.post(f"/api/submissions/{sub_id}/analyze", headers=headers)
    assert analyze_resp.status_code == 200, analyze_resp.text

    findings_resp = await api_client.get(f"/api/submissions/{sub_id}/findings", headers=headers)
    accessibility = [f for f in findings_resp.json() if f["category"] == "accessibility"]
    assert len(accessibility) == 1
    assert accessibility[0]["verdict"] == "needs_review"

    evidence_resp = await api_client.get(f"/api/submissions/{sub_id}/findings/{accessibility[0]['id']}/evidence", headers=headers)
    assert evidence_resp.status_code == 200
    assert evidence_resp.json()["status"] == "needs_review"
