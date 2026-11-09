from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.demand_analytics import VirtualStockReadFailed
from src.application.micromarket_loading.ports import MicromarketDeviceStockStore
from src.domain.micromarket_loading import MicromarketDeviceStock


@beartype
class VirtualStockHistory:
    """Virtual on-hand change points from micromarket device stock events."""

    def __init__(self, store: MicromarketDeviceStockStore) -> None:
        self._store = store

    @beartype
    def list_levels(
        self,
        *,
        machine_id: str,
        product_code: str,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[tuple[datetime, Decimal], ...] | VirtualStockReadFailed:
        del opened_at  # baseline taken from last point at/before lookback in policy
        try:
            events = tuple(self._store.list_events(machine_id))
        except Exception:
            return VirtualStockReadFailed()
        if not events:
            return ()
        levels: list[tuple[datetime, Decimal]] = []
        for index in range(len(events)):
            event = events[index]
            if event.occurred_at >= closed_at:
                break
            stock = MicromarketDeviceStock.rehydrate(
                machine_code=machine_id,
                events=events[: index + 1],
            )
            levels.append((event.occurred_at, stock.qty(product_code)))
        return tuple(levels)
