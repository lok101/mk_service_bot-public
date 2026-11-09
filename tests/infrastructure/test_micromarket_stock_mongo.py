from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.errors import MicromarketStockConcurrencyError
from src.infrastructure.mongodb.micromarket_stock import MongoMicromarketDeviceStockStore
from src.infrastructure.testing.micromarket_loading_fakes import InMemoryMicromarketDeviceStockStore


def test_micromarket_stock_rehydrate_sets_loaded_version() -> None:
    # happy
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-1",
    )
    events = stock.pull_events()
    loaded = MicromarketDeviceStock.rehydrate(machine_code="701", events=events)
    assert loaded.loaded_version == 1


def test_mongo_micromarket_stock_save_conflict_raises() -> None:
    # error: два агрегата с одной loaded_version
    import mongomock

    collection = mongomock.MongoClient().db.micromarket_stock_events
    store = MongoMicromarketDeviceStockStore.from_collection(collection)
    base = MicromarketDeviceStock(machine_code="701")
    base.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-1",
    )
    store.save(base)
    a = store.load("701")
    b = store.load("701")
    assert a is not None and b is not None
    a.apply_sale_deduct(
        sale_source_id="s-a",
        product_code="2311",
        qty=Decimal("1"),
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    b.apply_sale_deduct(
        sale_source_id="s-b",
        product_code="2311",
        qty=Decimal("1"),
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    store.save(a)
    with pytest.raises(MicromarketStockConcurrencyError):
        store.save(b)
    events = store.list_events("701")
    assert any(getattr(event, "sale_source_id", None) == "s-a" for event in events)


def test_memory_micromarket_stock_save_load_roundtrip() -> None:
    store = InMemoryMicromarketDeviceStockStore()
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-1",
    )
    store.save(stock)
    loaded = store.load("701")
    assert loaded is not None
    assert loaded.qty("2311") == Decimal("10")
    assert loaded.has_completed_inventory is True


def test_mongo_micromarket_stock_save_load_roundtrip() -> None:
    import mongomock

    collection = mongomock.MongoClient().db.micromarket_stock_events
    store = MongoMicromarketDeviceStockStore.from_collection(collection)

    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-1",
    )
    stock.apply_sale_deduct(
        sale_source_id="s1",
        product_code="2311",
        qty=Decimal("3"),
        occurred_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    store.save(stock)

    loaded = store.load("701")
    assert loaded is not None
    assert loaded.qty("2311") == Decimal("7")
    assert loaded.has_completed_inventory is True


def test_inventory_event_roundtrip_preserves_partial_true() -> None:
    from src.domain.ids import EventId
    from src.domain.micromarket_loading.events import MicromarketInventoryAccepted
    from src.infrastructure.mongodb.micromarket_stock_serialization import (
        micromarket_stock_event_from_document,
        micromarket_stock_event_to_document,
    )

    event = MicromarketInventoryAccepted(
        event_id=EventId("event-1"),
        machine_code="701",
        inventory_id="inv-p",
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities=(("2311", Decimal("3")),),
        occurred_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        partial=True,
    )
    doc = micromarket_stock_event_to_document(event, stream_version=1)
    assert doc["payload"]["partial"] is True
    restored = micromarket_stock_event_from_document(doc)
    assert isinstance(restored, MicromarketInventoryAccepted)
    assert restored.partial is True


def test_inventory_document_without_partial_defaults_to_false() -> None:
    from src.domain.micromarket_loading.events import MicromarketInventoryAccepted
    from src.infrastructure.mongodb.micromarket_stock_serialization import (
        micromarket_stock_event_from_document,
    )

    doc = {
        "event_id": "event-legacy",
        "machine_code": "701",
        "stream_version": 1,
        "occurred_at": datetime(2026, 9, 1, tzinfo=UTC),
        "event_type": "MicromarketInventoryAccepted",
        "payload": {
            "inventory_id": "inv-legacy",
            "as_of": datetime(2026, 9, 1, tzinfo=UTC),
            "quantities": [{"product_code": "2311", "quantity": "10"}],
        },
    }
    restored = micromarket_stock_event_from_document(doc)
    assert isinstance(restored, MicromarketInventoryAccepted)
    assert restored.partial is False


def test_mongo_partial_inventory_preserves_virtual_omit_on_reload() -> None:
    import mongomock

    collection = mongomock.MongoClient().db.micromarket_stock_events
    store = MongoMicromarketDeviceStockStore.from_collection(collection)
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        quantities={"2311": Decimal("4"), "2312": Decimal("2")},
        inventory_id="inv-a",
    )
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities={"2311": Decimal("3")},
        inventory_id="inv-b",
        partial=True,
    )
    store.save(stock)
    loaded = store.load("701")
    assert loaded is not None
    assert loaded.qty("2312") == Decimal("2")
    assert loaded.quantity_basis("2312") == "virtual"
    assert loaded.last_factual_qty("2312") == Decimal("2")
