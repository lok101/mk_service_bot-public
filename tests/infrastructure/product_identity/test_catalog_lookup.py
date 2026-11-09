from __future__ import annotations

from src.application.product_identity.models import CatalogProduct
from src.application.reference_data import ReferenceDataProvider, ReferenceDataSourceId
from src.infrastructure.product_identity.catalog_lookup import SnapshotCatalogProductLookup


def _provider_with(*rows: tuple[str, str, str, str]) -> ReferenceDataProvider:
    provider = ReferenceDataProvider()
    sheet = [["code", "name", "entity_kind", "archived"]]
    sheet.extend([list(row) for row in rows])
    provider.apply_rows(ReferenceDataSourceId.PRODUCT_CATALOG, sheet)
    return provider


def test_catalog_lookup_products_skip_bundles_and_keep_order() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind", "archived"],
            ["b", "Бета", "product", "false"],
            ["pack", "Набор", "bundle", "false"],
            ["a", "Альфа", "product", "true"],
        ],
    )
    found = SnapshotCatalogProductLookup(provider).products()
    assert found == (
        CatalogProduct(code="b", name="Бета", archived=False),
        CatalogProduct(code="a", name="Альфа", archived=True),
    )


def test_catalog_lookup_search_returns_at_most_50() -> None:
    provider = ReferenceDataProvider()
    rows = [["code", "name", "entity_kind", "archived"]]
    rows.extend([str(index), f"n{index}", "product", "false"] for index in range(60))
    provider.apply_rows(ReferenceDataSourceId.PRODUCT_CATALOG, rows)
    found = SnapshotCatalogProductLookup(provider).search("")
    assert len(found) == 50


def test_catalog_lookup_search_with_query_returns_at_most_50() -> None:
    provider = ReferenceDataProvider()
    rows = [["code", "name", "entity_kind"]]
    rows.extend([str(index), f"n{index}", "product"] for index in range(60))
    provider.apply_rows(ReferenceDataSourceId.PRODUCT_CATALOG, rows)
    found = SnapshotCatalogProductLookup(provider).search("N")
    assert len(found) == 50
    assert all(item.name.casefold().startswith("n") for item in found)


def test_catalog_lookup_number_collides_on_folded_d() -> None:
    provider = _provider_with(("D-1", "Чужой", "product", "false"))
    lookup = SnapshotCatalogProductLookup(provider)
    assert lookup.number_collides("d-1") is True
    assert lookup.number_collides("d-2") is False


def test_catalog_lookup_get_returns_trimmed_product_and_skips_bundle() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["2311", "Чай", "product"],
            ["bundle-1", "Комплект", "bundle"],
        ],
    )
    lookup = SnapshotCatalogProductLookup(provider)
    assert lookup.get(" 2311 ") == CatalogProduct(code="2311", name="Чай", archived=False)
    assert lookup.get("bundle-1") is None


def test_catalog_lookup_get_reads_archived() -> None:
    provider = _provider_with(("2311", "Чай", "product", "true"))
    found = SnapshotCatalogProductLookup(provider).get("2311")
    assert found == CatalogProduct(code="2311", name="Чай", archived=True)


def test_catalog_lookup_empty_snapshot() -> None:
    lookup = SnapshotCatalogProductLookup(ReferenceDataProvider())
    assert lookup.get("2311") is None
    assert lookup.search("") == ()
    assert lookup.search("чай") == ()
    assert lookup.number_collides("d-1") is False


def test_catalog_lookup_search_matches_code_and_name_ignoring_case() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["Ab-1", "Чай", "product"],
            ["zz", "Молоко", "product"],
        ],
    )
    lookup = SnapshotCatalogProductLookup(provider)
    by_code = lookup.search("ab-1")
    by_name = lookup.search("МОЛО")
    assert by_code == (CatalogProduct(code="Ab-1", name="Чай", archived=False),)
    assert by_name == (CatalogProduct(code="zz", name="Молоко", archived=False),)


def test_catalog_lookup_skips_bundles_in_search_and_collision() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["D-9", "Набор", "bundle"],
            ["p-1", "Чай", "product"],
        ],
    )
    lookup = SnapshotCatalogProductLookup(provider)
    assert lookup.search("набор") == ()
    assert lookup.number_collides("d-9") is False
    assert lookup.search("") == (CatalogProduct(code="p-1", name="Чай", archived=False),)
