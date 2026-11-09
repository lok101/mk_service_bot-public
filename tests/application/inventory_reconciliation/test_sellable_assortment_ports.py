from __future__ import annotations

from tests.application.inventory_reconciliation.sellable_fakes import (
    MappingSellableProductCodeCatalog,
)

from src.application.inventory_reconciliation.sellable_assortment_ports import (
    SellableProductCodeCatalog,
)


def test_mapping_fake_contains_strip_exact() -> None:
    catalog: SellableProductCodeCatalog = MappingSellableProductCodeCatalog(
        codes=frozenset({"P1", "DRINK1"}),
    )
    assert catalog.ready() is True
    assert catalog.contains("P1") is True
    assert catalog.contains("  P1  ") is True
    assert catalog.contains("p1") is False  # no casefold


def test_mapping_fake_not_ready() -> None:
    catalog = MappingSellableProductCodeCatalog(codes=frozenset({"P1"}), _ready=False)
    assert catalog.ready() is False
