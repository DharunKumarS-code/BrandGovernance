"""Phase 7 Stage 3, Stage 2: colour-consistency service -- focused tests."""

import cv2
import numpy as np

from app.models import AssetCreate, AssetStatus, AssetType, OrganisationCreate
from app.repositories import assets, organisations
from app.services.visual.colour_analysis import check_colour_consistency

APPROVED_BLUE_HEX = "#1458f2"


def _solid_png(rgb: tuple[int, int, int]) -> bytes:
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    img[:, :] = [rgb[2], rgb[1], rgb[0]]  # BGR
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


async def _org_with_approved_blue():
    org = await organisations.create(OrganisationCreate(name="Colour Test Org"))
    asset = await assets.create(
        AssetCreate(organisation_id=org.id, type=AssetType.COLOUR, name="Primary Blue", status=AssetStatus.APPROVED, hex_value=APPROVED_BLUE_HEX)
    )
    return org, asset


async def test_on_brand_colour_produces_no_finding():
    org, _asset = await _org_with_approved_blue()
    image = _solid_png((0x14, 0x58, 0xF2))  # exact approved hex
    findings = check_colour_consistency(image, await assets.list(organisation_id=org.id, limit=10))
    assert findings == []


async def test_clearly_off_brand_colour_is_contradicted_with_evidence():
    org, asset = await _org_with_approved_blue()
    image = _solid_png((255, 0, 0))  # bright red, far from approved blue
    findings = check_colour_consistency(image, await assets.list(organisation_id=org.id, limit=10))
    assert len(findings) == 1
    f = findings[0]
    assert f.category == "visual"
    assert f.verdict.value == "contradicted"
    assert f.evidence_record_type == "asset"
    assert f.evidence_record_id == asset.id
    assert "Primary Blue" in f.evidence_quote


async def test_neutral_colour_excluded_from_comparison():
    org, _asset = await _org_with_approved_blue()
    image = _solid_png((250, 250, 250))  # near-white, low saturation
    findings = check_colour_consistency(image, await assets.list(organisation_id=org.id, limit=10))
    assert findings == []


async def test_no_approved_colours_produces_no_findings():
    org = await organisations.create(OrganisationCreate(name="No Colours Org"))
    image = _solid_png((255, 0, 0))
    findings = check_colour_consistency(image, await assets.list(organisation_id=org.id, limit=10))
    assert findings == []  # nothing to judge against -- never a claim either way


async def test_findings_are_organisation_scoped_via_asset_list():
    org_a, _ = await _org_with_approved_blue()
    org_b = await organisations.create(OrganisationCreate(name="Colour Org B"))
    image = _solid_png((255, 0, 0))
    # org_b has no approved colours of its own -- must not see org_a's.
    findings = check_colour_consistency(image, await assets.list(organisation_id=org_b.id, limit=10))
    assert findings == []
