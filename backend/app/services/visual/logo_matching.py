"""Phase 7 Stage 3, Stage 3: logo-consistency checks via OpenCV template
matching. Same conventions as colour_analysis.py: confidence-banded,
returns plain RuleFinding containers, no DB/file I/O of its own (callers
pass pre-loaded asset + file-bytes pairs, keeping this pure/testable and
inherently organisation-scoped -- it only ever sees what it's given).

Known limitation (not solved here, by design): plain template matching is
NOT rotation- or distortion-invariant. A logo that's rotated, skewed, or
heavily cropped may go undetected even when present. A multi-scale
pyramid is used to tolerate resizing, not rotation.
"""

import cv2
import numpy as np

from app.models import Asset, AssetStatus, FindingSeverity, Verdict
from app.services.analysis.rules import RuleFinding

SCALES: tuple[float, ...] = (0.5, 0.75, 1.0, 1.25, 1.5)
MAX_IMAGE_DIM = 1600
# Below this normalized-correlation score, treat as "no meaningful match"
# -- say nothing. Never classify an unmatched/unrecognised mark as wrong.
REVIEW_MATCH = 0.60
# At or above this, a confident match.
CONFIDENT_MATCH = 0.80


def _decode_gray(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)


def _downscale(img: np.ndarray, max_dim: int = MAX_IMAGE_DIM) -> np.ndarray:
    h, w = img.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _best_match_score(target: np.ndarray, template: np.ndarray) -> float:
    """Best normalized-correlation match of `template` inside `target`
    across a small scale pyramid. 0.0 if it never fits."""
    best = 0.0
    th, tw = template.shape[:2]
    for scale in SCALES:
        w, h = max(1, int(tw * scale)), max(1, int(th * scale))
        if w < 8 or h < 8 or h > target.shape[0] or w > target.shape[1]:
            continue
        resized = cv2.resize(template, (w, h), interpolation=cv2.INTER_AREA)
        result = cv2.matchTemplate(target, resized, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(result)
        best = max(best, float(max_val))
    return best


def check_logo_consistency(image_bytes: bytes, logos: list[tuple[Asset, bytes]]) -> list[RuleFinding]:
    """Searches the submitted image for a region matching each known
    (approved or deprecated) logo asset. No logo assets -> [].

    - No meaningful match to a given logo -> say nothing (never "this mark
      is an unapproved logo" from absence of a match).
    - Confident match to an APPROVED logo -> nothing to flag (on-brand),
      consistent with colour_analysis.py not reporting on-brand matches.
    - Confident match to a DEPRECATED logo -> CONTRADICTED.
    - Ambiguous-confidence match to a DEPRECATED logo -> NEEDS_REVIEW.
    """
    if not logos:
        return []
    target = _decode_gray(image_bytes)
    if target is None:
        return []
    target = _downscale(target)

    findings: list[RuleFinding] = []
    for asset, file_bytes in logos:
        template = _decode_gray(file_bytes)
        if template is None:
            continue
        score = _best_match_score(target, template)
        if score < REVIEW_MATCH:
            continue
        if asset.status != AssetStatus.DEPRECATED:
            continue  # confident match to an approved logo -- not a problem

        verdict = Verdict.CONTRADICTED if score >= CONFIDENT_MATCH else Verdict.NEEDS_REVIEW
        severity = FindingSeverity.HIGH if verdict == Verdict.CONTRADICTED else FindingSeverity.MEDIUM
        certainty = (
            "This logo should no longer be used."
            if verdict == Verdict.CONTRADICTED
            else "Human review is recommended before concluding this is the deprecated logo."
        )
        findings.append(
            RuleFinding(
                category="visual",
                severity=severity,
                span_text=f"Logo region matching '{asset.name}' (confidence {score:.0%})",
                explanation=(
                    f"The submitted image contains a region matching the deprecated logo '{asset.name}' "
                    f"(match confidence {score:.0%}). {certainty}"
                ),
                verdict=verdict,
                evidence_record_type="asset",
                evidence_record_id=asset.id,
                evidence_quote=f"Deprecated logo '{asset.name}'",
            )
        )
    return findings
