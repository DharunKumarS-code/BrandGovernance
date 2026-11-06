"""Phase 8 Stage 4: WCAG colour-contrast accessibility check.

Reuses colour_analysis.py's dominant-colour extraction. IMPORTANT
LIMITATION -- read before changing anything here: k-means dominant-colour
clustering has no notion of WHICH pixels are text vs background; it only
reports what colours exist and how much area each covers. This module
therefore NEVER asserts a confirmed "text on background" pairing. Every
finding it produces is Verdict.NEEDS_REVIEW -- "the two most prominent
colours in this image have low contrast, which MAY affect text
readability if either is actually used for text; a human should check" --
never a confirmed accessibility violation. Reliable text/background
identification would need real text-region detection (OCR or stroke/edge
analysis), which this architecture does not have; if that's ever added,
this module can be revisited to produce a firmer verdict.
"""

from app.models import FindingSeverity, Verdict
from app.services.analysis.rules import RuleFinding
from app.services.visual.colour_analysis import _dominant_colours

# WCAG 2.x AA thresholds.
AA_NORMAL_TEXT_RATIO = 4.5
AA_LARGE_TEXT_RATIO = 3.0
# Same floor as colour_analysis.py's palette check -- ignore minor
# colours, only genuinely prominent pairs are even considered.
MIN_PIXEL_FRACTION = 0.08


def _srgb_to_linear(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int]) -> float:
    """WCAG contrast ratio: (L1+0.05)/(L2+0.05), L1 the lighter colour.
    Always >= 1.0 (1.0 for identical colours)."""
    l1, l2 = _relative_luminance(rgb1), _relative_luminance(rgb2)
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)


def check_colour_contrast(image_bytes: bytes) -> list[RuleFinding]:
    """Flags a low-contrast dominant-colour pair as NEEDS_REVIEW -- never
    a confirmed violation (see module docstring). Needs at least two
    sufficiently prominent dominant colours to compare; otherwise []."""
    significant = [(rgb, frac) for rgb, frac in _dominant_colours(image_bytes) if frac >= MIN_PIXEL_FRACTION]
    if len(significant) < 2:
        return []

    (rgb_a, frac_a), (rgb_b, frac_b) = significant[0], significant[1]
    ratio = contrast_ratio(rgb_a, rgb_b)
    if ratio >= AA_NORMAL_TEXT_RATIO:
        return []  # passes WCAG AA even for normal text -- nothing to flag

    hex_a, hex_b = "#%02x%02x%02x" % rgb_a, "#%02x%02x%02x" % rgb_b
    fails_large_text_too = ratio < AA_LARGE_TEXT_RATIO
    severity = FindingSeverity.MEDIUM if fails_large_text_too else FindingSeverity.LOW
    tail = (
        " and even for large text (3:1)." if fails_large_text_too else ", though it passes the lower large-text threshold (3:1)."
    )

    return [
        RuleFinding(
            category="accessibility",
            severity=severity,
            span_text=f"Colour pair {hex_a} / {hex_b} (contrast {ratio:.1f}:1)",
            explanation=(
                f"The two most prominent colours in this image ({hex_a}, ~{frac_a:.0%} of the image, and "
                f"{hex_b}, ~{frac_b:.0%}) have a contrast ratio of {ratio:.1f}:1, below the WCAG AA threshold "
                f"for normal text (4.5:1){tail} This does NOT confirm a real accessibility issue -- "
                "dominant-colour extraction cannot reliably tell whether these colours are actually used as "
                "text and background in this image. Human review is required before acting on this."
            ),
            verdict=Verdict.NEEDS_REVIEW,
            evidence_record_type=None,
            evidence_record_id=None,
            evidence_quote=None,
        )
    ]
