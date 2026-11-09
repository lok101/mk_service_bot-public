from __future__ import annotations

from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.provider import ReferenceDataProvider
from src.infrastructure.reference_data.provider_sellable_catalog import (
    ProviderSellableProductCodeCatalog,
)


def test_sellable_catalog_contains_strip_exact() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [
            ["code", "name", "entity_kind"],
            ["P1", "Snack One", "product"],
            ["DRINK1", "Latte", "bundle"],
        ],
    )
    catalog = ProviderSellableProductCodeCatalog(provider=provider)
    assert catalog.ready() is True
    assert catalog.contains("P1") is True
    assert catalog.contains("  P1") is True
    assert catalog.contains("DRINK1") is True


def test_sellable_catalog_rejects_casefold_mismatch() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [["code", "name", "entity_kind"], ["P1", "Snack One", "product"]],
    )
    catalog = ProviderSellableProductCodeCatalog(provider=provider)
    assert catalog.contains("p1") is False


def test_sellable_catalog_not_ready_when_none() -> None:
    provider = ReferenceDataProvider()
    catalog = ProviderSellableProductCodeCatalog(provider=provider)
    assert catalog.ready() is False
    assert catalog.contains("P1") is False


def test_sellable_catalog_not_ready_when_only_bundles() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [["code", "name", "entity_kind"], ["DRINK1", "Latte", "bundle"]],
    )
    catalog = ProviderSellableProductCodeCatalog(provider=provider)
    assert catalog.ready() is False
