from __future__ import annotations

from decimal import Decimal

from src.application.form_inventory_policy import (
    COFFEE_LOADING_PROFILE_ID,
    COFFEE_REVISION_PROFILE_ID,
    TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID,
    FormInventoryPolicyLine,
    MemoryFormInventoryPolicyStore,
    ensure_coffee_policy_profiles,
    seed_coffee_ingredient_policies,
)
from src.domain.quantities import QuantityInputMode


def test_policy_upsert_and_get() -> None:
    store = MemoryFormInventoryPolicyStore()
    ensure_coffee_policy_profiles(store)
    line = FormInventoryPolicyLine(
        domain_number="d-1",
        min_qty=Decimal("0"),
        max_qty=Decimal("12"),
        radio_n=8,
    )
    store.upsert_line(COFFEE_LOADING_PROFILE_ID, line)
    loaded = store.get_line(COFFEE_LOADING_PROFILE_ID, "d-1")
    assert loaded == line
    profile = store.get_profile(COFFEE_LOADING_PROFILE_ID)
    assert profile is not None
    assert profile.input_mode is QuantityInputMode.PACKAGE_COUNT


def test_missing_line_none() -> None:
    store = MemoryFormInventoryPolicyStore()
    ensure_coffee_policy_profiles(store)
    assert store.get_line(COFFEE_LOADING_PROFILE_ID, "d-missing") is None


def test_list_lines_orders_by_sort_order() -> None:
    store = MemoryFormInventoryPolicyStore()
    ensure_coffee_policy_profiles(store)
    store.upsert_line(
        COFFEE_REVISION_PROFILE_ID,
        FormInventoryPolicyLine(
            domain_number="d-2",
            min_qty=Decimal("0"),
            max_qty=Decimal("10"),
            sort_order=2,
            form_label="Второй",
            form_hint="",
        ),
    )
    store.upsert_line(
        COFFEE_REVISION_PROFILE_ID,
        FormInventoryPolicyLine(
            domain_number="d-1",
            min_qty=Decimal("0"),
            max_qty=Decimal("10"),
            sort_order=1,
            form_label="Первый",
            form_hint="верх",
        ),
    )
    lines = store.list_lines(COFFEE_REVISION_PROFILE_ID)
    assert [line.domain_number for line in lines] == ["d-1", "d-2"]
    assert lines[0].form_label == "Первый"
    assert lines[0].form_hint == "верх"


def test_line_defaults_empty_presentation() -> None:
    line = FormInventoryPolicyLine(
        domain_number="d-9",
        min_qty=Decimal("0"),
        max_qty=Decimal("1"),
    )
    assert line.sort_order == 0
    assert line.form_label == ""
    assert line.form_hint == ""


def test_mongo_legacy_line_defaults_and_round_trip() -> None:
    import mongomock

    from src.infrastructure.form_inventory_policy.mongo_store import (
        MongoFormInventoryPolicyStore,
    )

    collection = mongomock.MongoClient().db.form_inventory_policies
    store = MongoFormInventoryPolicyStore.from_collection(collection)
    ensure_coffee_policy_profiles(store)
    collection.replace_one(
        {"_id": f"line:{COFFEE_REVISION_PROFILE_ID}:d-legacy"},
        {
            "_id": f"line:{COFFEE_REVISION_PROFILE_ID}:d-legacy",
            "doc_kind": "line",
            "profile_id": COFFEE_REVISION_PROFILE_ID,
            "domain_number": "d-legacy",
            "min_qty": "0",
            "max_qty": "5",
        },
        upsert=True,
    )
    legacy = store.get_line(COFFEE_REVISION_PROFILE_ID, "d-legacy")
    assert legacy is not None
    assert legacy.sort_order == 0
    assert legacy.form_label == ""
    assert legacy.form_hint == ""

    store.upsert_line(
        COFFEE_REVISION_PROFILE_ID,
        FormInventoryPolicyLine(
            domain_number="d-new",
            min_qty=Decimal("1"),
            max_qty=Decimal("3"),
            sort_order=4,
            form_label="Коротко",
            form_hint="снизу",
        ),
    )
    loaded = store.get_line(COFFEE_REVISION_PROFILE_ID, "d-new")
    assert loaded is not None
    assert loaded.sort_order == 4
    assert loaded.form_label == "Коротко"
    assert loaded.form_hint == "снизу"
    listed = store.list_lines(COFFEE_REVISION_PROFILE_ID)
    assert [line.domain_number for line in listed] == ["d-legacy", "d-new"]


def test_seed_coffee_ingredient_policies_per_profile() -> None:
    store = MemoryFormInventoryPolicyStore()
    seed_coffee_ingredient_policies(
        store,
        domain_number="d-7",
        loading=FormInventoryPolicyLine(
            domain_number="d-7",
            min_qty=Decimal("0"),
            max_qty=Decimal("6"),
            radio_n=6,
        ),
        revision=FormInventoryPolicyLine(
            domain_number="d-7",
            min_qty=Decimal("0"),
            max_qty=Decimal("4999"),
        ),
        warehouse=FormInventoryPolicyLine(
            domain_number="d-7",
            min_qty=Decimal("0"),
            max_qty=Decimal("12"),
        ),
    )
    loading = store.get_line(COFFEE_LOADING_PROFILE_ID, "d-7")
    assert loading is not None
    assert loading.radio_n == 6
    assert loading.max_qty == Decimal("6")
    revision = store.get_line(COFFEE_REVISION_PROFILE_ID, "d-7")
    assert revision is not None
    assert revision.max_qty == Decimal("4999")
    assert revision.radio_n is None
    warehouse = store.get_line(TECHNICIAN_WAREHOUSE_COFFEE_PROFILE_ID, "d-7")
    assert warehouse is not None
    assert warehouse.max_qty == Decimal("12")
    assert warehouse.radio_n is None
