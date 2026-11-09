from __future__ import annotations

from src.application.reference_data.models import (
    APP_REFERENCE_DATA_SOURCE_IDS,
    ReferenceDataSourceId,
    compute_content_hash,
)


def test_source_ids_have_stable_values() -> None:
    assert ReferenceDataSourceId.BOT_USERS.value == "bot_users"
    assert ReferenceDataSourceId.PRODUCT_CATALOG.value == "product_catalog"


def test_source_id_coffee_and_snack_values() -> None:
    assert ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS.value == (
        "coffee_technician_locations"
    )
    assert ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS.value == ("snack_technician_locations")


def test_app_source_ids_contain_coffee_and_snack() -> None:
    assert ReferenceDataSourceId.COFFEE_TECHNICIAN_LOCATIONS in APP_REFERENCE_DATA_SOURCE_IDS
    assert ReferenceDataSourceId.SNACK_TECHNICIAN_LOCATIONS in APP_REFERENCE_DATA_SOURCE_IDS
    assert not hasattr(ReferenceDataSourceId, "TECHNICIAN_LOCATIONS") or (
        "technician_locations" not in {m.value for m in ReferenceDataSourceId}
    )


def test_product_vitrine_and_ms_catalog_enum_values() -> None:
    assert ReferenceDataSourceId.PRODUCT_VITRINE.value == "product_vitrine"
    assert ReferenceDataSourceId.PRODUCT_CATALOG.value == "product_catalog"


def test_app_source_ids_contain_vitrine_not_ms_catalog() -> None:
    assert ReferenceDataSourceId.PRODUCT_VITRINE in APP_REFERENCE_DATA_SOURCE_IDS
    assert ReferenceDataSourceId.PRODUCT_CATALOG not in APP_REFERENCE_DATA_SOURCE_IDS


def test_locations_directory_not_in_app_source_ids() -> None:
    assert ReferenceDataSourceId.LOCATIONS_DIRECTORY.value == "locations_directory"
    assert ReferenceDataSourceId.LOCATIONS_DIRECTORY not in APP_REFERENCE_DATA_SOURCE_IDS


def test_content_hash_is_stable_and_prefixed() -> None:
    rows = [["id", "имя"], ["1", "Кофе"]]
    first = compute_content_hash(rows)
    second = compute_content_hash([["id", "имя"], ["1", "Кофе"]])
    assert first == second
    assert first.startswith("sha256:")


def test_content_hash_changes_with_content() -> None:
    assert compute_content_hash([["a"]]) != compute_content_hash([["b"]])
