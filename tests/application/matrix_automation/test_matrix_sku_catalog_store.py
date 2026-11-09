from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)


def _entry(code: str, name: str = "N", capacity: int = 1) -> MatrixSkuCatalogEntry:
    return MatrixSkuCatalogEntry(
        product_code=code,
        display_name=name,
        capacity=capacity,
        product_multiplier=Decimal("1"),
    )


def test_memory_upsert_get() -> None:
    store = InMemoryMatrixSkuCatalogStore()
    store.upsert(_entry("P1", "One"))
    got = store.get("P1")
    assert got is not None
    assert got.display_name == "One"
    assert store.get("missing") is None


def test_memory_list_all() -> None:
    store = InMemoryMatrixSkuCatalogStore()
    store.upsert(_entry("B"))
    store.upsert(_entry("A"))
    codes = {e.product_code for e in store.list_all()}
    assert codes == {"A", "B"}


def test_memory_allows_duplicate_display_names() -> None:
    store = InMemoryMatrixSkuCatalogStore()
    store.upsert(_entry("A", "Same"))
    store.upsert(_entry("B", "Same"))
    assert {e.product_code for e in store.list_all()} == {"A", "B"}
