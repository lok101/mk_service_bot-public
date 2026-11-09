from __future__ import annotations

from src.infrastructure.testing.kitshop_ingest_fakes import InMemoryKitShopSaleReceiptStore


def test_memory_receipt_load_missing_is_none() -> None:
    # edge
    store = InMemoryKitShopSaleReceiptStore()
    assert store.load(100) is None


def test_memory_receipt_save_is_idempotent_on_sale_id() -> None:
    # happy + idempotency: второй payload не затирает первый
    store = InMemoryKitShopSaleReceiptStore()
    first = {"SaleId": 100, "marker": "first"}
    second = {"SaleId": 100, "marker": "second"}
    store.save_if_absent(sale_id=100, payload=first)
    store.save_if_absent(sale_id=100, payload=second)
    assert store.load(100) == first
    assert store.load(200) is None
