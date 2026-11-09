from __future__ import annotations

from datetime import UTC, datetime

import mongomock

from src.application.inventory_reconciliation.sale_skip import MachineSaleSkip
from src.infrastructure.mongodb.machine_sales_skipped import MongoMachineSaleSkipStore
from src.infrastructure.testing.machine_sales_skipped_fakes import InMemoryMachineSaleSkipStore


def _skip(
    *,
    source_id: str = "kit:1:01.05.2026 12:00:00:2:5",
    last_seen_at: datetime | None = None,
) -> MachineSaleSkip:
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    return MachineSaleSkip(
        source_id=source_id,
        reason_class="critical_product_resolve",
        kit_vending_machine_id=1,
        vending_machine_name="101 Coffee",
        occurred_at=now,
        line_number=2,
        matrix_id=5,
        goods_name="X",
        external_id=None,
        first_seen_at=now,
        last_seen_at=last_seen_at or now,
    )


def test_skip_store_upsert_and_delete_by_source_id() -> None:
    store = InMemoryMachineSaleSkipStore()
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    skip = _skip()
    store.upsert(skip)
    again = skip.__class__(
        **{**skip.__dict__, "last_seen_at": datetime(2026, 8, 5, 13, 0, tzinfo=UTC)},
    )
    store.upsert(again)
    got = store.get(skip.source_id)
    assert got is not None
    assert got.first_seen_at == now
    assert got.last_seen_at == datetime(2026, 8, 5, 13, 0, tzinfo=UTC)
    assert store.delete_by_source_id(skip.source_id) is True
    assert store.get(skip.source_id) is None


def test_mongo_skip_store_upsert_roundtrip_unique_and_delete() -> None:
    collection = mongomock.MongoClient().db.machine_sales_skipped
    store = MongoMachineSaleSkipStore.from_collection(collection)
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
    later = datetime(2026, 8, 5, 13, 0, tzinfo=UTC)

    store.upsert(_skip())
    store.upsert(_skip(last_seen_at=later))

    got = store.get("kit:1:01.05.2026 12:00:00:2:5")
    assert got is not None
    assert got.first_seen_at == now
    assert got.last_seen_at == later
    assert collection.count_documents({}) == 1

    indexes = collection.index_information()
    assert "machine_sales_skipped_source_id_unique" in indexes
    assert indexes["machine_sales_skipped_source_id_unique"]["unique"] is True

    assert store.delete_by_source_id("kit:1:01.05.2026 12:00:00:2:5") is True
    assert store.get("kit:1:01.05.2026 12:00:00:2:5") is None
    assert store.delete_by_source_id("kit:1:01.05.2026 12:00:00:2:5") is False
