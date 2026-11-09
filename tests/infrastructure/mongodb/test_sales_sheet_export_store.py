from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import mongomock

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.mongodb.machine_sales import MongoMachineSalesStore
from src.infrastructure.mongodb.sales_sheet_export_cursor import (
    MongoSalesSheetExportCursorStore,
)
from src.infrastructure.sales_monitoring.mongo_sales_for_sheet_export import (
    MongoSalesForSheetExportLoader,
)


def _sale(i: int) -> MachineSale:
    return MachineSale(
        source_id=f"src-{i}",
        machine_id=MachineId("vm-1"),
        product_code="P",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i),
        ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
        sale_kind="coffee",
        machine_code="1",
        price=Decimal("10"),
    )


def _loader() -> tuple[MongoSalesForSheetExportLoader, mongomock.collection.Collection]:
    client = mongomock.MongoClient()
    collection = client["test"]["machine_sales"]
    store = MongoMachineSalesStore.from_collection(collection)
    for i in range(5):
        assert store.insert_if_absent(_sale(i)) is True
    return MongoSalesForSheetExportLoader.from_collection(collection), collection


def test_list_latest_orders_ascending_for_export() -> None:
    loader, _ = _loader()
    got = loader.list_latest(limit=3)
    assert [s.source_id for s in got] == ["src-2", "src-3", "src-4"]


def test_list_after_respects_cursor_and_limit() -> None:
    loader, _ = _loader()
    pivot = _sale(1)
    got = loader.list_after(
        occurred_at=pivot.occurred_at,
        source_id=pivot.source_id,
        limit=2,
    )
    assert [s.source_id for s in got] == ["src-2", "src-3"]


def test_list_after_tie_breaks_on_source_id() -> None:
    client = mongomock.MongoClient()
    collection = client["test"]["machine_sales"]
    store = MongoMachineSalesStore.from_collection(collection)
    ts = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    for source_id in ("src-a", "src-b", "src-c"):
        sale = MachineSale(
            source_id=source_id,
            machine_id=MachineId("vm-1"),
            product_code="P",
            quantity=Decimal("1"),
            occurred_at=ts,
            ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
            sale_kind="coffee",
            machine_code="1",
            price=Decimal("10"),
        )
        assert store.insert_if_absent(sale) is True
    loader = MongoSalesForSheetExportLoader.from_collection(collection)
    got = loader.list_after(occurred_at=ts, source_id="src-a", limit=10)
    assert [s.source_id for s in got] == ["src-b", "src-c"]


def test_from_collection_ensures_occurred_at_source_id_index() -> None:
    client = mongomock.MongoClient()
    collection = client["test"]["machine_sales"]
    MongoSalesForSheetExportLoader.from_collection(collection)
    indexes = collection.index_information()
    assert "machine_sales_occurred_at_source_id" in indexes
    assert indexes["machine_sales_occurred_at_source_id"]["key"] == [
        ("occurred_at", 1),
        ("source_id", 1),
    ]


def test_export_cursor_roundtrip_global() -> None:
    client = mongomock.MongoClient()
    collection = client["test"]["sales_sheet_export_cursors"]
    store = MongoSalesSheetExportCursorStore.from_collection(collection)
    assert store.load() is None
    ts = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
    store.save(occurred_at=ts, source_id="abc")
    assert store.load() == (ts, "abc")
    store.save(occurred_at=ts, source_id="def")
    assert store.load() == (ts, "def")
    doc = collection.find_one({"_id": "global"})
    assert doc is not None
    assert doc["source_id"] == "def"
