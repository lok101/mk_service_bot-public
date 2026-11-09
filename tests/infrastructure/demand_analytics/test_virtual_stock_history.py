from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import EventId
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.events import (
    MicromarketLoadingApplied,
    MicromarketSaleDeducted,
    MicromarketStockEvent,
)
from src.infrastructure.demand_analytics.virtual_stock_history import VirtualStockHistory

_T0 = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
_T1 = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
_T2 = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 10, 10, 0, 0, tzinfo=UTC)


class _EventStore:
    def __init__(self, events: tuple[MicromarketStockEvent, ...]) -> None:
        self._events = events

    def load(self, machine_code: str) -> MicromarketDeviceStock | None:
        if not self._events:
            return None
        return MicromarketDeviceStock.rehydrate(machine_code=machine_code, events=self._events)

    def save(self, stock: MicromarketDeviceStock) -> None:
        del stock

    def list_events(self, machine_code: str) -> tuple[MicromarketStockEvent, ...]:
        del machine_code
        return self._events


class _BrokenStore(_EventStore):
    def __init__(self) -> None:
        super().__init__(())

    def list_events(self, machine_code: str) -> tuple[MicromarketStockEvent, ...]:
        del machine_code
        raise RuntimeError("stock store down")


def test_list_levels_tracks_qty_after_load_and_sale() -> None:
    events: tuple[MicromarketStockEvent, ...] = (
        MicromarketLoadingApplied(
            event_id=EventId("e1"),
            machine_code="701",
            loading_run_id="run-1",
            lines=(("2311", Decimal("5")),),
            occurred_at=_T0,
        ),
        MicromarketSaleDeducted(
            event_id=EventId("e2"),
            machine_code="701",
            sale_source_id="sale-1",
            product_code="2311",
            qty=Decimal("5"),
            occurred_at=_T1,
        ),
        MicromarketLoadingApplied(
            event_id=EventId("e3"),
            machine_code="701",
            loading_run_id="run-2",
            lines=(("9999", Decimal("1")),),
            occurred_at=_T2,
        ),
    )
    history = VirtualStockHistory(_EventStore(events))
    levels = history.list_levels(
        machine_id="701",
        product_code="2311",
        opened_at=_T0,
        closed_at=_CLOSED,
    )
    assert levels == (
        (_T0, Decimal("5")),
        (_T1, Decimal("0")),
        (_T2, Decimal("0")),
    )


def test_list_levels_store_error_is_read_failed() -> None:
    from src.application.demand_analytics import VirtualStockReadFailed

    history = VirtualStockHistory(_BrokenStore())
    result = history.list_levels(
        machine_id="701",
        product_code="2311",
        opened_at=_T0,
        closed_at=_CLOSED,
    )
    assert isinstance(result, VirtualStockReadFailed)
