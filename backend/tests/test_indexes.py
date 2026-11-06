from app.core.db import INDEX_SPECS, db, ensure_indexes


async def test_ensure_indexes_creates_expected_indexes():
    await ensure_indexes()

    for collection_name in INDEX_SPECS:
        info = await db[collection_name].index_information()
        indexed_fields = set()
        for spec in info.values():
            for field, _direction in spec["key"]:
                indexed_fields.add(field)
        assert "_id" in indexed_fields


async def test_brand_facts_has_subject_attribute_compound_index():
    await ensure_indexes()
    info = await db["brand_facts"].index_information()
    compound = [spec["key"] for spec in info.values() if len(spec["key"]) == 2]
    assert [("subject", 1), ("attribute", 1)] in compound


async def test_ensure_indexes_is_idempotent():
    await ensure_indexes()
    await ensure_indexes()  # must not raise on re-run
    info = await db["submissions"].index_information()
    assert len(info) >= 1
