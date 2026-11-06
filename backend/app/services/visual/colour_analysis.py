"""Phase 7 Stage 3, Stage 2: dominant-colour brand-consistency checks.

Lightweight, explainable, no ML: k-means dominant-colour extraction (cv2)
+ Lab-space distance (perceptually closer to human colour judgement than
raw RGB). Confidence-banded, same spirit as app/services/analysis/rules.py
-- a colour is only flagged when clearly off-brand; ambiguous cases are
NEEDS_REVIEW, never a hard claim, and an org with no approved colours
produces no findings at all (nothing to judge against).

Returns plain RuleFinding containers (reused from rules.py, same shape
the orchestrator already knows how to persist) -- not wired into
analyze_submission() yet; that's Stage 4.
"""

import cv2
import numpy as np

from app.models import Asset, FindingSeverity, Verdict
from app.services.analysis.rules import RuleFinding

# Ignore any dominant colour covering less than this fraction of the
# image -- a minor accent is not a brand-colour claim.
MIN_PIXEL_FRACTION = 0.08
# Lab-space Euclidean distance (CIE76 ΔE) below which a colour counts as
# an on-brand match -- no finding.
MATCH_DELTA_E = 12.0
# Above this, confidently off-brand. Between MATCH_DELTA_E and this, the
# match is ambiguous -- NEEDS_REVIEW, never a hard claim.
CONFIDENT_DELTA_E = 30.0
# Near-white/black/gray pixels are common background/text colours, not a
# brand-colour claim -- excluded from comparison entirely (HSV S channel).
NEUTRAL_SATURATION_MAX = 20


def _dominant_colours(image_bytes: bytes, k: int = 6) -> list[tuple[tuple[int, int, int], float]]:
    """Returns up to k (rgb, pixel_fraction) pairs, largest cluster first."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)  # BGR, alpha dropped
    if img is None:
        return []
    h, w = img.shape[:2]
    scale = min(1.0, 200 / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    pixels = img.reshape(-1, 3).astype(np.float32)
    k = min(k, len(pixels))
    if k < 1:
        return []
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.5)
    _compactness, labels, centers = cv2.kmeans(pixels, k, None, criteria, 5, cv2.KMEANS_PP_CENTERS)

    counts = np.bincount(labels.flatten(), minlength=k)
    total = int(counts.sum())
    out = []
    for i in range(k):
        b, g, r = centers[i]
        rgb = (int(round(r)), int(round(g)), int(round(b)))
        out.append((rgb, counts[i] / total))
    out.sort(key=lambda pair: pair[1], reverse=True)
    return out


def _is_neutral(rgb: tuple[int, int, int]) -> bool:
    bgr = np.uint8([[list(reversed(rgb))]])
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[0][0]
    return int(hsv[1]) <= NEUTRAL_SATURATION_MAX


def _to_lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    bgr = np.uint8([[list(reversed(rgb))]])
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)[0][0]
    return float(lab[0]), float(lab[1]), float(lab[2])


def _delta_e(lab1: tuple[float, float, float], lab2: tuple[float, float, float]) -> float:
    return float(np.sqrt(sum((a - b) ** 2 for a, b in zip(lab1, lab2))))


def _hex_to_rgb(hex_value: str) -> tuple[int, int, int] | None:
    h = hex_value.lstrip("#")
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def check_colour_consistency(image_bytes: bytes, approved_colours: list[Asset]) -> list[RuleFinding]:
    """Compares the image's significant dominant colours against this
    organisation's approved colour assets. No approved colours registered
    -> returns [] (nothing to judge against, never a claim either way)."""
    approved = [(a, _hex_to_rgb(a.hex_value)) for a in approved_colours if a.hex_value]
    approved = [(a, rgb) for a, rgb in approved if rgb is not None]
    if not approved:
        return []
    approved_lab = [(a, _to_lab(rgb)) for a, rgb in approved]

    findings: list[RuleFinding] = []
    for rgb, fraction in _dominant_colours(image_bytes):
        if fraction < MIN_PIXEL_FRACTION or _is_neutral(rgb):
            continue
        lab = _to_lab(rgb)
        closest_asset, closest_lab = min(approved_lab, key=lambda pair: _delta_e(lab, pair[1]))
        delta_e = _delta_e(lab, closest_lab)
        if delta_e <= MATCH_DELTA_E:
            continue  # on-brand -- nothing to flag

        hex_value = "#%02x%02x%02x" % rgb
        verdict = Verdict.CONTRADICTED if delta_e > CONFIDENT_DELTA_E else Verdict.NEEDS_REVIEW
        severity = (
            FindingSeverity.HIGH if (verdict == Verdict.CONTRADICTED and fraction > 0.2) else FindingSeverity.MEDIUM
        )
        certainty = (
            "This is a clear mismatch."
            if verdict == Verdict.CONTRADICTED
            else "The match is ambiguous -- human review recommended."
        )
        findings.append(
            RuleFinding(
                category="visual",
                severity=severity,
                span_text=f"Dominant colour {hex_value} ({fraction:.0%} of image)",
                explanation=(
                    f"A dominant image colour ({hex_value}, ~{fraction:.0%} of the image) does not closely "
                    f"match any approved brand colour. Closest: '{closest_asset.name}' "
                    f"({closest_asset.hex_value}), colour difference (dE) {delta_e:.1f}. {certainty}"
                ),
                verdict=verdict,
                evidence_record_type="asset",
                evidence_record_id=closest_asset.id,
                evidence_quote=f"Approved colour '{closest_asset.name}' ({closest_asset.hex_value})",
            )
        )
    return findings
