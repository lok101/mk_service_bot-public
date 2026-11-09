from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.domain.micromarket_loading.pending_invent import PendingMicromarketInvent
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryPendingMicromarketInventStore,
)

_MACHINE = "701"
_NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_DAY = date(2026, 11, 3)


def _pending(inventory_id: str = "inv-1", qty: str = "2") -> PendingMicromarketInvent:
    return PendingMicromarketInvent(
        machine_code=_MACHINE,
        inventory_id=inventory_id,
        quantities=(("d-1", Decimal(qty)),),
        submitted_at=_NOW,
        operational_day=_DAY,
    )


def test_save_and_get_pending() -> None:
    store = InMemoryPendingMicromarketInventStore()
    store.save(_pending())
    loaded = store.get_for_machine(_MACHINE)
    assert loaded is not None
    assert loaded.inventory_id == "inv-1"
    assert loaded.quantity_map()["d-1"] == Decimal("2")


def test_save_replaces_same_machine() -> None:
    store = InMemoryPendingMicromarketInventStore()
    store.save(_pending("inv-1", "2"))
    store.save(_pending("inv-2", "5"))
    loaded = store.get_for_machine(_MACHINE)
    assert loaded is not None
    assert loaded.inventory_id == "inv-2"
    assert loaded.quantity_map()["d-1"] == Decimal("5")


def test_clear_removes_pending() -> None:
    store = InMemoryPendingMicromarketInventStore()
    store.save(_pending())
    store.clear(_MACHINE)
    assert store.get_for_machine(_MACHINE) is None
