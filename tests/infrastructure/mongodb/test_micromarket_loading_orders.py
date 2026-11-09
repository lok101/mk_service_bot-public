from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import mongomock
import pytest

from src.domain.micromarket_loading.errors import MicromarketLoadingConcurrencyError
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.infrastructure.mongodb.micromarket_loading_orders import (
    MongoMicromarketLoadingOrderStore,
    micromarket_loading_order_event_from_document,
)

_TZ = ZoneInfo("Europe/Moscow")


def test_order_store_roundtrip_replays_launch_intent_before_open() -> None:
    collection = mongomock.MongoClient()["test"]["micromarket_loading_order_events"]
    store = MongoMicromarketLoadingOrderStore(collection)
    line = DraftLine(
        product_code="2311",
        target_qty=4,
        stock_qty=Decimal("1"),
        need_qty=Decimal("3"),
        launch_qty=Decimal("2"),
    )
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.save_draft((line,))
    cycle.record_launch_intent(order_id="order-pending")
    store.save(cycle)
    loaded = store.load("701")
    assert loaded is not None
    assert loaded.order_id == "order-pending"
    assert loaded.status is None

    loaded.open_order(
        order_id="order-pending",
        move_id="move-1",
        lines=(line,),
        opened_at=datetime(2026, 9, 24, 10, 0, tzinfo=_TZ),
        timezone=_TZ,
        day_end_hour=6,
    )
    store.save(loaded)
    restored = store.load("701")
    assert restored is not None
    assert restored.status is OrderStatus.OPEN
    assert restored.order_id == "order-pending"


def test_order_store_roundtrip_replays_open() -> None:
    collection = mongomock.MongoClient()["test"]["micromarket_loading_order_events"]
    store = MongoMicromarketLoadingOrderStore(collection)
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.open_order(
        order_id="order-1",
        move_id="move-1",
        lines=(
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
        opened_at=datetime(2026, 9, 24, 10, 0, tzinfo=_TZ),
        timezone=_TZ,
        day_end_hour=6,
    )
    store.save(cycle)
    loaded = store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.OPEN
    assert loaded.order_id == "order-1"

    # Edge: second save with empty pending inserts nothing.
    before = collection.count_documents({})
    store.save(loaded)
    assert collection.count_documents({}) == before


def test_legacy_order_recounted_without_shelf_before_decodes_as_none() -> None:
    """Legacy OrderRecounted payload without shelf_before → None (not empty tuple)."""
    from src.domain.micromarket_loading.order_events import OrderRecounted

    event = micromarket_loading_order_event_from_document(
        {
            "event_type": "OrderRecounted",
            "payload": {
                "deltas": [{"product_code": "2311", "quantity": "1"}],
                "at": datetime(2026, 9, 24, 10, 0, tzinfo=UTC),
            },
        },
    )
    assert isinstance(event, OrderRecounted)
    assert event.shelf_before is None

    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.open_order(
        order_id="order-1",
        move_id="move-1",
        lines=(
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
        opened_at=datetime(2026, 9, 24, 10, 0, tzinfo=_TZ),
        timezone=_TZ,
        day_end_hour=6,
    )
    opened = cycle.pull_events()
    restored = MicromarketLoadingCycle.rehydrate(
        machine_code="701",
        events=(*opened, event),
    )
    assert restored.status is OrderStatus.RECOUNTED
    assert restored.shelf_before is None


def test_order_store_roundtrip_replays_recount_with_shelf_before_and_replace() -> None:
    collection = mongomock.MongoClient()["test"]["micromarket_loading_order_events"]
    store = MongoMicromarketLoadingOrderStore(collection)
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.open_order(
        order_id="order-1",
        move_id="move-1",
        lines=(
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
        opened_at=datetime(2026, 9, 24, 10, 0, tzinfo=_TZ),
        timezone=_TZ,
        day_end_hour=6,
    )
    shelf_before = (("2311", Decimal("1")),)
    cycle.mark_recounted(
        at=datetime(2026, 9, 24, 10, 0, tzinfo=_TZ),
        deltas=(("2311", Decimal("1")),),
        shelf_before=shelf_before,
    )
    cycle.replace_recount_deltas(
        at=datetime(2026, 9, 24, 11, 0, tzinfo=_TZ),
        deltas=(("2311", Decimal("-2")),),
    )
    store.save(cycle)
    loaded = store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.RECOUNTED
    assert loaded.shelf_before == shelf_before
    assert loaded.deltas == (("2311", Decimal("-2")),)


def test_order_store_rejects_stale_loaded_version_on_concurrent_open() -> None:
    """error: two loads at same version cannot both append OrderOpened."""
    collection = mongomock.MongoClient()["test"]["micromarket_loading_order_events"]
    store = MongoMicromarketLoadingOrderStore(collection)
    line = DraftLine(
        product_code="2311",
        target_qty=4,
        stock_qty=Decimal("1"),
        need_qty=Decimal("3"),
        launch_qty=Decimal("2"),
    )
    seed = MicromarketLoadingCycle(machine_code="705")
    seed.save_draft((line,))
    seed.record_launch_intent(order_id="order-race")
    store.save(seed)

    first = store.load("705")
    second = store.load("705")
    assert first is not None and second is not None
    assert first.loaded_version == second.loaded_version

    first.open_order(
        order_id="order-race",
        move_id="move-a",
        lines=(line,),
        opened_at=datetime(2026, 10, 28, 10, 0, tzinfo=_TZ),
        timezone=_TZ,
        day_end_hour=6,
    )
    store.save(first)

    second.open_order(
        order_id="order-race",
        move_id="move-b",
        lines=(line,),
        opened_at=datetime(2026, 10, 28, 10, 0, tzinfo=_TZ),
        timezone=_TZ,
        day_end_hour=6,
    )
    with pytest.raises(MicromarketLoadingConcurrencyError):
        store.save(second)

    restored = store.load("705")
    assert restored is not None
    assert restored.status is OrderStatus.OPEN
    assert restored.move_id == "move-a"
    opened = [
        doc
        for doc in collection.find({"machine_code": "705"})
        if doc["event_type"] == "OrderOpened"
    ]
    assert len(opened) == 1


def test_order_store_roundtrip_replays_alert_recorded() -> None:
    from datetime import date

    collection = mongomock.MongoClient()["test"]["micromarket_loading_order_events"]
    store = MongoMicromarketLoadingOrderStore(collection)
    cycle = MicromarketLoadingCycle(machine_code="701")
    cycle.open_order(
        order_id="order-1",
        move_id="move-1",
        lines=(
            DraftLine(
                product_code="2311",
                target_qty=4,
                stock_qty=Decimal("1"),
                need_qty=Decimal("3"),
                launch_qty=Decimal("2"),
            ),
        ),
        opened_at=datetime(2026, 9, 24, 10, 0, tzinfo=_TZ),
        timezone=_TZ,
        day_end_hour=6,
    )
    store.save(cycle)
    loaded = store.load("701")
    assert loaded is not None
    loaded.record_alert(order_id="order-1", operational_day=date(2026, 9, 24))
    store.save(loaded)
    restored = store.load("701")
    assert restored is not None
    assert restored.was_alerted(order_id="order-1", operational_day=date(2026, 9, 24))
    listed = store.list_cycles()
    assert len(listed) == 1
    assert listed[0].machine_code == "701"
