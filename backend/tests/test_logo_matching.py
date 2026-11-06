"""Phase 7 Stage 3, Stage 3: logo-matching service -- focused tests."""

import cv2
import numpy as np

from app.models import AssetCreate, AssetStatus, AssetType, OrganisationCreate
from app.repositories import assets, organisations
from app.services.visual.logo_matching import check_logo_consistency


def _logo_array(fill: int = 60) -> np.ndarray:
    arr = np.full((40, 40), fill, dtype=np.uint8)
    arr[10:30, 10:30] = 255 - fill  # distinctive inner pattern, not flat
    return arr


def _encode(arr: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", arr)
    assert ok
    return buf.tobytes()


def _embed(logo: np.ndarray, canvas: int = 160, pos: tuple[int, int] = (60, 70), bg: int = 128) -> bytes:
    out = np.full((canvas, canvas), bg, dtype=np.uint8)
    h, w = logo.shape
    y, x = pos
    out[y : y + h, x : x + w] = logo
    return _encode(out)


async def _make_logo_asset(org_id, status: AssetStatus, name: str):
    return await assets.create(AssetCreate(organisation_id=org_id, type=AssetType.LOGO, name=name, status=status, file_path=None))


async def test_confident_deprecated_logo_match_is_contradicted():
    org = await organisations.create(OrganisationCreate(name="Logo Test Org"))
    asset = await _make_logo_asset(org.id, AssetStatus.DEPRECATED, "Old Logo")
    logo = _logo_array()
    submission_image = _embed(logo)

    findings = check_logo_consistency(submission_image, [(asset, _encode(logo))])
    assert len(findings) == 1
    f = findings[0]
    assert f.verdict.value == "contradicted"
    assert f.category == "visual"
    assert f.evidence_record_type == "asset"
    assert f.evidence_record_id == asset.id


async def test_confident_approved_logo_match_produces_no_finding():
    org = await organisations.create(OrganisationCreate(name="Logo Test Org Approved"))
    asset = await _make_logo_asset(org.id, AssetStatus.APPROVED, "Current Logo")
    logo = _logo_array()
    submission_image = _embed(logo)

    findings = check_logo_consistency(submission_image, [(asset, _encode(logo))])
    assert findings == []  # on-brand -- nothing to flag


async def test_logo_absent_from_image_produces_no_finding():
    org = await organisations.create(OrganisationCreate(name="Logo Test Org Absent"))
    asset = await _make_logo_asset(org.id, AssetStatus.DEPRECATED, "Old Logo")
    logo = _logo_array()
    # Flat, featureless background -- the logo is simply not present.
    blank = _encode(np.full((160, 160), 128, dtype=np.uint8))

    findings = check_logo_consistency(blank, [(asset, _encode(logo))])
    assert findings == []  # never claim a mismatch from a non-match


async def test_no_logo_assets_registered_produces_no_findings():
    logo = _logo_array()
    submission_image = _embed(logo)
    findings = check_logo_consistency(submission_image, [])
    assert findings == []
