from app.repositories import (
    assets,
    brand_facts,
    claim_policies,
    organisations,
    revisions,
    submissions,
    terminology,
    users,
)
from app.seed import DEMO_ORG_NAME, seed


async def _get_demo_org_id():
    found = await organisations.list(filter={"name": DEMO_ORG_NAME}, limit=1)
    assert found
    return found[0].id


async def test_seed_populates_all_demo_collections():
    await seed()
    org_id = await _get_demo_org_id()

    assert len(await users.list(organisation_id=org_id)) == 3
    assert 6 <= len(await brand_facts.list(organisation_id=org_id)) <= 8
    assert 5 <= len(await terminology.list(organisation_id=org_id)) <= 6
    assert 4 <= len(await claim_policies.list(organisation_id=org_id)) <= 5

    org_assets = await assets.list(organisation_id=org_id)
    colours = [a for a in org_assets if a.type.value == "colour"]
    logos = [a for a in org_assets if a.type.value == "logo"]
    assert 3 <= len(colours) <= 4
    assert len(logos) == 2
    assert {a.status.value for a in logos} == {"approved", "deprecated"}

    org_submissions = await submissions.list(organisation_id=org_id)
    assert 4 <= len(org_submissions) <= 5
    for submission in org_submissions:
        subs_revisions = await revisions.list(organisation_id=org_id, filter={"submission_id": submission.id})
        assert len(subs_revisions) == 1


async def test_seed_has_one_expired_brand_fact():
    await seed()
    org_id = await _get_demo_org_id()

    facts = await brand_facts.list(organisation_id=org_id)
    expired = [f for f in facts if f.valid_to is not None]
    assert len(expired) == 1


async def test_seed_is_safe_to_rerun():
    await seed()
    org_id_first = await _get_demo_org_id()
    user_count_first = len(await users.list(organisation_id=org_id_first))

    await seed()
    org_id_second = await _get_demo_org_id()
    user_count_second = len(await users.list(organisation_id=org_id_second))

    # Re-running clears and recreates the demo org: counts stay stable and no
    # duplicate demo organisations pile up.
    assert user_count_first == user_count_second == 3
    all_demo_orgs = await organisations.list(filter={"name": DEMO_ORG_NAME})
    assert len(all_demo_orgs) == 1
