from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import mongomock

from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.mongodb.machine_sales import MongoMachineSalesStore
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore


def _sale(*, occurred_at: datetime, source_id: str) -> MachineSale:
    return MachineSale(
        source_id=source_id,
        machine_id=MachineId("m1"),
        product_code="P1",
        quantity=Decimal("1"),
        occurred_at=occurred_at,
        ingested_at=occurred_at,
        sale_kind="snack",
        machine_code="M1",
        price=Decimal("100.00"),
    )


def test_find_in_global_window_half_open() -> None:
    store = InMemoryMachineSalesStore()
    start = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    store.insert_if_absent(_sale(occurred_at=start, source_id="a"))  # included
    store.insert_if_absent(
        _sale(occurred_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC), source_id="b"),
    )
    store.insert_if_absent(_sale(occurred_at=end, source_id="c"))  # excluded (half-open)
    got = store.find_in_global_window(opened_at=start, closed_at=end)
    assert {s.source_id for s in got} == {"a", "b"}


def test_find_in_global_window_mongo_bounds() -> None:
    collection = mongomock.MongoClient().db.machine_sales
    store = MongoMachineSalesStore.from_collection(collection)
    start = datetime(2026, 8, 9, 0, 0, tzinfo=UTC)
    end = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    store.insert_if_absent(_sale(occurred_at=start, source_id="a"))
    store.insert_if_absent(
        _sale(occurred_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC), source_id="b"),
    )
    store.insert_if_absent(_sale(occurred_at=end, source_id="c"))
    got = store.find_in_global_window(opened_at=start, closed_at=end)
    assert {s.source_id for s in got} == {"a", "b"}
    assert [s.source_id for s in got] == ["a", "b"]
