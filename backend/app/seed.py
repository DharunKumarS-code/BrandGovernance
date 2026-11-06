"""Seed a fictional demo brand ("Nova Electronics") for local development and demos.

Safe to re-run: it clears every record belonging to the demo organisation
(matched by name) before reseeding, and never touches any other organisation.
"""

import asyncio
import struct
import zlib
from datetime import datetime, timezone

from app.core.db import client, ensure_indexes
from app.core.storage import ASSETS_DIR, asset_file_path, delete_if_exists, ensure_storage_dirs, write_bytes
from app.models import (
    AssetCreate,
    AssetStatus,
    AssetType,
    BrandFactCreate,
    ClaimPolicyCreate,
    ClaimPolicyStatus,
    GuidelineDocCreate,
    GuidelineDocStatus,
    OrganisationCreate,
    RevisionCreate,
    SubmissionCreate,
    SubmissionStatus,
    TerminologyCreate,
    UserCreate,
    UserRole,
)
from app.repositories import (
    assets,
    brand_facts,
    claim_policies,
    guideline_docs,
    organisations,
    revisions,
    submissions,
    terminology,
    users,
)

DEMO_ORG_NAME = "Nova Electronics"

# Sample ad copy with planted mistakes (wrong spec, outdated price, banned
# terms, unsupported superlatives). Seeded as real submissions below, and
# also reused directly by the "Load sample ad" feature in the Phase 4
# submissions API (app/routers/submissions.py) so the frontend's one-click
# demo content is the actual seed data, not a separate hardcoded copy.
SAMPLE_AD_COPY: list[tuple[str, str]] = [
    ("Nova Buds Pro - Summer Launch Ad",
     "Nova Buds Pro deliver 12 hours of non-stop playback on a single charge. "
     "Grab yours today!"),  # wrong spec (actual: 8 hours)
    ("Nova Buds Pro - Flash Sale Banner",
     "Get Nova Buds Pro for just $129 -- today only!"),  # outdated price (now $149)
    ("Nova Buds Pro - Lifestyle Social Post",
     "Nova Buds Pro are completely waterproof, so wear them in the shower."),  # banned term
    ("Nova Buds Pro - Hero Banner Copy",
     "The #1 earbuds in the world, guaranteed to outperform anything else on the market."),  # unsupported superlative + banned term
    ("Nova Home Hub - Wellness Campaign Copy",
     "Nova Home Hub is clinically proven to improve your sleep by 40%."),  # banned term + unsupported claim
]


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _make_solid_png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A minimal solid-colour PNG, built with only the stdlib (struct/zlib)
    -- no imaging library needed for two flat demo swatches. Used so the
    seeded logo assets are real PNG files Phase 8's OpenCV comparison can
    actually load, rather than Phase 2's placeholder (non-existent) paths."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB, no interlace
    row = b"\x00" + bytes(rgb) * width  # filter byte 0 (none) + RGB pixels
    raw = row * height
    idat = zlib.compress(raw)
    return signature + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


async def clear_demo_org() -> None:
    existing = await organisations.list(filter={"name": DEMO_ORG_NAME}, limit=1)
    if not existing:
        return
    org_id = existing[0].id

    # Remove any on-disk files belonging to this org's assets before
    # dropping the DB records -- otherwise each reseed (new asset _ids each
    # time) would leave the previous run's logo files orphaned on disk.
    old_assets = await assets.list(organisation_id=org_id, limit=1000)
    for asset in old_assets:
        if asset.file_path:
            delete_if_exists(ASSETS_DIR / asset.file_path)

    for repo in (
        users,
        guideline_docs,
        brand_facts,
        terminology,
        claim_policies,
        assets,
        revisions,
        submissions,
    ):
        await repo.delete_many({"organisation_id": org_id})
    await organisations.delete_many({"_id": org_id})


async def seed() -> None:
    await ensure_indexes()
    ensure_storage_dirs()
    await clear_demo_org()

    org = await organisations.create(OrganisationCreate(name=DEMO_ORG_NAME))
    org_id = org.id

    admin = await users.create(
        UserCreate(organisation_id=org_id, name="Avery Chen", email="avery.admin@novaelectronics.demo", role=UserRole.ADMIN)
    )
    creator = await users.create(
        UserCreate(organisation_id=org_id, name="Priya Nair", email="priya.creator@novaelectronics.demo", role=UserRole.CREATOR)
    )
    await users.create(
        UserCreate(organisation_id=org_id, name="Jordan Lee", email="jordan.reviewer@novaelectronics.demo", role=UserRole.REVIEWER)
    )

    guideline_doc = await guideline_docs.create(
        GuidelineDocCreate(
            organisation_id=org_id,
            title="Nova Electronics Brand & Product Guidelines",
            filename="nova_brand_guidelines.pdf",
            uploaded_by=admin.id,
            page_count=24,
            status=GuidelineDocStatus.READY,
        )
    )
    doc_id = guideline_doc.id

    fact_rows = [
        # subject, attribute, value, unit, valid_from, valid_to, page, quote
        ("Nova Buds Pro", "battery_life", "8", "hours", _dt(2025, 1, 15), None, 4,
         "Nova Buds Pro deliver up to 8 hours of playback on a single charge."),
        ("Nova Buds Pro", "price", "129", "USD", _dt(2025, 1, 15), _dt(2025, 6, 1), 5,
         "Nova Buds Pro launches at an introductory price of $129."),
        ("Nova Buds Pro", "price", "149", "USD", _dt(2025, 6, 1), None, 5,
         "Starting June 2025, Nova Buds Pro is priced at $149."),
        ("Nova Buds Pro", "weight", "4.5", "g", _dt(2025, 1, 15), None, 6,
         "Each earbud weighs just 4.5 grams."),
        ("Nova Buds Pro", "charging_time", "1.5", "hours", _dt(2025, 1, 15), None, 6,
         "A full charge takes approximately 1.5 hours via the USB-C case."),
        ("Nova Buds Pro", "water_resistance", "IPX4", None, _dt(2025, 1, 15), None, 7,
         "Nova Buds Pro carry an IPX4 splash-resistance rating."),
        ("Nova Home Hub", "warranty", "2", "years", _dt(2025, 2, 1), None, 14,
         "Nova Home Hub is covered by a 2-year limited warranty."),
        ("Nova Home Hub", "price", "199", "USD", _dt(2025, 2, 1), None, 15,
         "Nova Home Hub retails for $199."),
    ]
    for subject, attribute, value, unit, valid_from, valid_to, page, quote in fact_rows:
        await brand_facts.create(
            BrandFactCreate(
                organisation_id=org_id,
                subject=subject,
                attribute=attribute,
                value=value,
                unit=unit,
                valid_from=valid_from,
                valid_to=valid_to,
                source_doc_id=doc_id,
                page=page,
                quote=quote,
            )
        )

    terminology_rows = [
        ("Nova Buds Pro", ["NovaBuds Pro", "Nova Bud Pro", "Nova buds pro"],
         "Official product name must match brand style guide capitalization."),
        ("Nova Home Hub", ["NovaHub", "Nova Hub", "Home Hub by Nova"],
         "Use the full approved product name on first mention."),
        ("noise cancellation", ["noise canceling", "noise-cancelling tech", "ANC magic"],
         "Use brand-approved spelling and avoid marketing slang."),
        ("Nova Electronics", ["Nova Electronic", "NovaElectronics", "Nova Corp"],
         "Legal entity name must be used exactly as registered."),
        ("water-resistant", ["waterproof", "water proof"],
         "Product is IPX4 (splash resistant), not waterproof; 'waterproof' is a regulatory overclaim."),
        ("up to 8 hours of playback", ["all-day battery", "unlimited battery"],
         "Avoid vague or unsubstantiated battery claims."),
    ]
    for preferred_term, banned_variants, reason in terminology_rows:
        await terminology.create(
            TerminologyCreate(
                organisation_id=org_id,
                preferred_term=preferred_term,
                banned_variants=banned_variants,
                reason=reason,
            )
        )

    claim_policy_rows = [
        ("#1", ClaimPolicyStatus.NEEDS_EVIDENCE, "Must cite the specific ranking source and date."),
        ("best", ClaimPolicyStatus.NEEDS_EVIDENCE, "Must cite comparative evidence or qualify the claim (e.g. 'best in its price range')."),
        ("guaranteed", ClaimPolicyStatus.BANNED, None),
        ("clinically proven", ClaimPolicyStatus.BANNED, None),
        ("award-winning", ClaimPolicyStatus.NEEDS_EVIDENCE, "Must name the award and issuing body."),
    ]
    for pattern, status, disclaimer in claim_policy_rows:
        await claim_policies.create(
            ClaimPolicyCreate(organisation_id=org_id, pattern=pattern, status=status, required_disclaimer=disclaimer)
        )

    palette = [
        ("Nova Blue", "#1458F2"),
        ("Nova Graphite", "#2B2D33"),
        ("Nova Mist", "#E7ECF5"),
        ("Nova Coral", "#FF6B5B"),
    ]
    for name, hex_value in palette:
        await assets.create(
            AssetCreate(organisation_id=org_id, type=AssetType.COLOUR, name=name, status=AssetStatus.APPROVED, hex_value=hex_value)
        )
    # Real PNG files (not Phase 2's placeholder, non-existent SVG paths) so
    # the asset-file-serving endpoint and Phase 8's planned OpenCV logo
    # comparison both have actual images to work with. Visibly different
    # solid colours -- Nova Blue vs. a muted retired-grey -- so a simple
    # pixel/colour comparison can tell them apart. SVG is no longer
    # accepted anywhere after the Phase 3 security audit.
    logo_rows = [
        ("Nova Electronics Primary Logo", AssetStatus.APPROVED, (0x14, 0x58, 0xF2)),  # Nova Blue
        ("Nova Electronics Logo (2022, retired)", AssetStatus.DEPRECATED, (0x9A, 0xA3, 0xB2)),  # muted grey
    ]
    for name, logo_status, rgb in logo_rows:
        logo = await assets.create(
            AssetCreate(organisation_id=org_id, type=AssetType.LOGO, name=name, status=logo_status, file_path=None)
        )
        png_bytes = _make_solid_png(128, 128, rgb)
        write_bytes(asset_file_path(logo.id, ".png"), png_bytes)
        await assets.update(logo.id, {"file_path": f"{logo.id}.png"}, organisation_id=org_id)

    # Raw demo content for later review phases, not Finding records --
    # findings get generated in Phase 5+.
    for title, ad_text in SAMPLE_AD_COPY:
        submission = await submissions.create(
            SubmissionCreate(
                organisation_id=org_id,
                title=title,
                creator_id=creator.id,
                current_revision=1,
                status=SubmissionStatus.PENDING_REVIEW,
            )
        )
        await revisions.create(
            RevisionCreate(
                organisation_id=org_id,
                submission_id=submission.id,
                version=1,
                content=ad_text,
                content_type="text/plain",
                author_id=creator.id,
            )
        )

    print(f"Seeded demo organisation '{DEMO_ORG_NAME}' ({org_id}).")


async def main() -> None:
    await seed()
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
