"""Unit tests for app/services/analysis/claims.py -- the deterministic
claim-vs-brand-fact comparison engine (section E: Python code, never the
LLM, performs the actual comparison) and the regex-based degraded-mode
extractor (section F fallback)."""

from datetime import datetime, timezone

from app.models import BrandFactCreate, Verdict
from app.repositories import brand_facts
from app.services.analysis.claims import ExtractedClaim, compare_claim_to_brand_facts, extract_claims_via_rules

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


async def _seed_nova_facts(org_id):
    rows = [
        ("Nova Buds Pro", "battery_life", "8", "hours", datetime(2025, 1, 15, tzinfo=timezone.utc), None, "8 hours of playback."),
        ("Nova Buds Pro", "price", "129", "USD", datetime(2025, 1, 15, tzinfo=timezone.utc), datetime(2025, 6, 1, tzinfo=timezone.utc), "Intro price $129."),
        ("Nova Buds Pro", "price", "149", "USD", datetime(2025, 6, 1, tzinfo=timezone.utc), None, "Now $149."),
        ("Nova Buds Pro", "charging_time", "1.5", "hours", datetime(2025, 1, 15, tzinfo=timezone.utc), None, "1.5h to charge."),
        ("Nova Buds Pro", "water_resistance", "IPX4", None, datetime(2025, 1, 15, tzinfo=timezone.utc), None, "IPX4 rated."),
    ]
    created = []
    for subject, attribute, value, unit, valid_from, valid_to, quote in rows:
        created.append(
            await brand_facts.create(
                BrandFactCreate(
                    organisation_id=org_id, subject=subject, attribute=attribute, value=value, unit=unit,
                    valid_from=valid_from, valid_to=valid_to, quote=quote,
                )
            )
        )
    return created


async def test_verified_when_claim_matches_current_fact(demo_headers):
    _headers, org, _user = demo_headers
    facts = await _seed_nova_facts(org.id)
    price_facts = [f for f in facts if f.attribute == "price"]

    claim = ExtractedClaim(subject="Nova Buds Pro", attribute="price", value="149", unit="USD", source_quote="$149")
    result = compare_claim_to_brand_facts(claim, price_facts, NOW)
    assert result.verdict == Verdict.VERIFIED
    assert result.matched_fact.value == "149"


async def test_outdated_when_claim_matches_an_expired_fact(demo_headers):
    _headers, org, _user = demo_headers
    facts = await _seed_nova_facts(org.id)
    price_facts = [f for f in facts if f.attribute == "price"]

    claim = ExtractedClaim(subject="Nova Buds Pro", attribute="price", value="129", unit="USD", source_quote="$129")
    result = compare_claim_to_brand_facts(claim, price_facts, NOW)
    assert result.verdict == Verdict.OUTDATED
    assert result.matched_fact.value == "129"


async def test_contradicted_when_claim_value_never_matches_any_fact(demo_headers):
    _headers, org, _user = demo_headers
    facts = await _seed_nova_facts(org.id)
    battery_facts = [f for f in facts if f.attribute == "battery_life"]

    claim = ExtractedClaim(subject="Nova Buds Pro", attribute="battery_life", value="12", unit="hours", source_quote="12 hours")
    result = compare_claim_to_brand_facts(claim, battery_facts, NOW)
    assert result.verdict == Verdict.CONTRADICTED
    assert result.matched_fact is None


async def test_unsupported_when_no_fact_exists_for_the_attribute_at_all():
    claim = ExtractedClaim(subject="Nova Home Hub", attribute="sleep_improvement", value="40", unit="%", source_quote="40%")
    result = compare_claim_to_brand_facts(claim, [], NOW)
    assert result.verdict == Verdict.UNSUPPORTED


async def test_needs_review_when_units_cannot_be_compared(demo_headers):
    _headers, org, _user = demo_headers
    facts = await _seed_nova_facts(org.id)
    battery_facts = [f for f in facts if f.attribute == "battery_life"]

    # Claims a value in an unrecognised/incompatible unit for this attribute.
    claim = ExtractedClaim(subject="Nova Buds Pro", attribute="battery_life", value="480", unit="furlongs", source_quote="480 furlongs")
    result = compare_claim_to_brand_facts(claim, battery_facts, NOW)
    assert result.verdict == Verdict.NEEDS_REVIEW


async def test_unit_normalization_minutes_to_hours(demo_headers):
    _headers, org, _user = demo_headers
    facts = await _seed_nova_facts(org.id)
    battery_facts = [f for f in facts if f.attribute == "battery_life"]

    # 480 minutes == 8 hours -- should normalize and match as VERIFIED.
    claim = ExtractedClaim(subject="Nova Buds Pro", attribute="battery_life", value="480", unit="minutes", source_quote="480 minutes")
    result = compare_claim_to_brand_facts(claim, battery_facts, NOW)
    assert result.verdict == Verdict.VERIFIED


async def test_non_numeric_value_exact_match(demo_headers):
    _headers, org, _user = demo_headers
    facts = await _seed_nova_facts(org.id)
    water_facts = [f for f in facts if f.attribute == "water_resistance"]

    claim = ExtractedClaim(subject="Nova Buds Pro", attribute="water_resistance", value="IPX4", unit=None, source_quote="IPX4")
    result = compare_claim_to_brand_facts(claim, water_facts, NOW)
    assert result.verdict == Verdict.VERIFIED

    wrong_claim = ExtractedClaim(subject="Nova Buds Pro", attribute="water_resistance", value="IPX8", unit=None, source_quote="IPX8")
    wrong_result = compare_claim_to_brand_facts(wrong_claim, water_facts, NOW)
    assert wrong_result.verdict == Verdict.CONTRADICTED


async def test_regex_degraded_extractor_finds_planted_battery_mistake(demo_headers):
    _headers, org, _user = demo_headers
    facts = await _seed_nova_facts(org.id)
    content = "Nova Buds Pro deliver 12 hours of non-stop playback on a single charge. Grab yours today!"

    claims = extract_claims_via_rules(content, facts)
    battery_claims = [c for c in claims if c.attribute == "battery_life"]
    assert len(battery_claims) == 1
    assert battery_claims[0].value == "12"
    assert battery_claims[0].subject == "Nova Buds Pro"


async def test_regex_degraded_extractor_ignores_unmentioned_subjects(demo_headers):
    _headers, org, _user = demo_headers
    await _seed_nova_facts(org.id)
    content = "Some totally unrelated product costs $50."
    claims = extract_claims_via_rules(content, await brand_facts.list(organisation_id=org.id, limit=100))
    assert claims == []
