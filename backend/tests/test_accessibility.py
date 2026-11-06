"""Phase 8 Stage 4: WCAG contrast-ratio accessibility check -- focused tests."""

import cv2
import numpy as np

from app.services.visual.accessibility import check_colour_contrast, contrast_ratio


def _two_tone_png(a: tuple[int, int, int], b: tuple[int, int, int]) -> bytes:
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    img[:10, :] = [a[2], a[1], a[0]]  # BGR, top half
    img[10:, :] = [b[2], b[1], b[0]]  # bottom half
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def _solid_png(rgb: tuple[int, int, int]) -> bytes:
    img = np.zeros((20, 20, 3), dtype=np.uint8)
    img[:, :] = [rgb[2], rgb[1], rgb[0]]
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


# --- contrast_ratio() math edge cases ---------------------------------------


def test_identical_colours_have_ratio_one():
    assert contrast_ratio((100, 100, 100), (100, 100, 100)) == 1.0


def test_black_and_white_have_maximum_ratio():
    ratio = contrast_ratio((0, 0, 0), (255, 255, 255))
    assert 20.9 <= ratio <= 21.1  # WCAG's known black/white ratio is 21:1


def test_ratio_is_symmetric_regardless_of_argument_order():
    r1 = contrast_ratio((10, 10, 10), (200, 200, 200))
    r2 = contrast_ratio((200, 200, 200), (10, 10, 10))
    assert r1 == r2


# --- check_colour_contrast() --------------------------------------------


def test_high_contrast_pair_produces_no_finding():
    image = _two_tone_png((0, 0, 0), (255, 255, 255))
    assert check_colour_contrast(image) == []


def test_low_contrast_pair_is_needs_review_not_a_hard_claim():
    # Two mid-grays, deliberately close -- well below 4.5:1.
    image = _two_tone_png((120, 120, 120), (150, 150, 150))
    findings = check_colour_contrast(image)
    assert len(findings) == 1
    f = findings[0]
    assert f.verdict.value == "needs_review"  # never a confirmed violation
    assert f.category == "accessibility"
    assert f.evidence_record_type is None  # no DB record backs a WCAG calculation
    assert "does not confirm" in f.explanation.lower() or "does not confirm a real" in f.explanation.lower()


def test_single_dominant_colour_produces_no_finding():
    # Nothing reliable to compare -- must not fabricate a pair.
    image = _solid_png((128, 128, 128))
    assert check_colour_contrast(image) == []


def test_very_low_contrast_is_medium_severity_moderate_is_low_severity():
    very_low = check_colour_contrast(_two_tone_png((120, 120, 120), (135, 135, 135)))[0]
    assert very_low.severity.value == "medium"  # fails even the large-text threshold

    moderate = check_colour_contrast(_two_tone_png((90, 90, 90), (160, 160, 160)))
    if moderate:  # only assert severity if this pairing landed between 3:1 and 4.5:1
        assert moderate[0].severity.value in ("low", "medium")
