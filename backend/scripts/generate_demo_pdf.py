"""Generates the Nova Electronics demo guideline PDF using PyMuPDF.

Content here must match app/seed.py exactly -- same facts, terminology,
claim policies and brand colours -- so that uploading this PDF through the
real guideline upload endpoint produces extracted text consistent with
what's already seeded for Nova Electronics. Run from backend/:

    python scripts/generate_demo_pdf.py
"""

from pathlib import Path

import fitz  # PyMuPDF

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "demo-assets" / "nova_electronics_brand_guidelines.pdf"

PAGE_WIDTH, PAGE_HEIGHT = 612, 792  # US Letter
MARGIN = 54
LINE_HEIGHT = 16
TITLE_SIZE = 16
HEADING_SIZE = 12
BODY_SIZE = 10


def draw_page(doc: "fitz.Document", title: str, sections: list[tuple[str, list[str]]]) -> None:
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = MARGIN
    page.insert_text((MARGIN, y), title, fontsize=TITLE_SIZE, fontname="helv")
    y += LINE_HEIGHT * 2

    for heading, lines in sections:
        page.insert_text((MARGIN, y), heading, fontsize=HEADING_SIZE, fontname="helv")
        y += LINE_HEIGHT
        for line in lines:
            if y > PAGE_HEIGHT - MARGIN:
                break
            page.insert_text((MARGIN, y), line, fontsize=BODY_SIZE, fontname="helv")
            y += LINE_HEIGHT
        y += LINE_HEIGHT // 2


def build() -> None:
    doc = fitz.open()

    draw_page(
        doc,
        "Nova Electronics -- Brand & Product Guidelines",
        [
            ("Introduction", [
                "Nova Electronics designs consumer audio and smart-home products.",
                "This guide defines approved product facts, terminology and claim rules.",
            ]),
            ("Product specifications -- Nova Buds Pro", [
                "Battery life: up to 8 hours of playback on a single charge.",
                "Price: $149 (effective June 2025; launch price was $129).",
                "Weight: 4.5 grams per earbud.",
                "Charging time: approximately 1.5 hours via the USB-C case.",
                "Water resistance: IPX4 splash-resistance rating.",
            ]),
            ("Product specifications -- Nova Home Hub", [
                "Warranty: 2-year limited warranty.",
                "Price: $199.",
            ]),
            ("Approved product claims", [
                "Claims about battery life, weight, charging time and water",
                "resistance must match the specifications above exactly.",
            ]),
        ],
    )

    draw_page(
        doc,
        "Nova Electronics -- Terminology & Claims",
        [
            ("Approved terminology", [
                "Nova Buds Pro (not NovaBuds Pro, Nova Bud Pro, or Nova buds pro).",
                "Nova Home Hub (not NovaHub, Nova Hub, or Home Hub by Nova).",
                "noise cancellation (not noise canceling, noise-cancelling tech, or ANC magic).",
                "Nova Electronics (not Nova Electronic, NovaElectronics, or Nova Corp).",
                "water-resistant (not waterproof or water proof) -- product is IPX4, splash",
                "resistant, not fully waterproof.",
                "up to 8 hours of playback (not all-day battery or unlimited battery).",
            ]),
            ("Brand tone and voice", [
                "Confident, precise and evidence-based. Avoid hype and vague superlatives.",
            ]),
            ("Claim policies", [
                "#1: needs evidence -- must cite the specific ranking source and date.",
                "best: needs evidence -- must cite comparative evidence or qualify the claim.",
                "guaranteed: banned -- do not use.",
                "clinically proven: banned -- do not use.",
                "award-winning: needs evidence -- must name the award and issuing body.",
            ]),
        ],
    )

    draw_page(
        doc,
        "Nova Electronics -- Visual Identity",
        [
            ("Approved brand colour palette", [
                "Nova Blue: #1458F2",
                "Nova Graphite: #2B2D33",
                "Nova Mist: #E7ECF5",
                "Nova Coral: #FF6B5B",
            ]),
            ("Logo usage", [
                "Use the current primary logo at full contrast on approved backgrounds only.",
                "The 2022 logo is deprecated and must not appear in new materials.",
            ]),
            ("Additional communication rules", [
                "Always use approved terminology and cite evidence for any claim marked",
                "'needs evidence'. Never use a banned claim pattern in any form.",
            ]),
        ],
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT_PATH)
    doc.close()
    print(f"Wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
