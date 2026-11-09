from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import MachineId


@runtime_checkable
class _MachineSalesFreshnessSource(Protocol):
    def last_occurred_at(self, machine_id: MachineId) -> datetime | None: ...

    def load_global_cursor(self) -> datetime | None: ...


@beartype
@dataclass(frozen=True, slots=True)
class MachineSalesStoreFreshnessLookup:
    store: _MachineSalesFreshnessSource
    last_sale_lookup_days: int
    clock: Callable[[], datetime] | None = None

    @beartype
    def last_sale_at(self, machine_id: MachineId) -> datetime | None:
        last = self.store.last_occurred_at(machine_id)
        if last is None:
            return None
        now = self.clock() if self.clock is not None else datetime.now(UTC)
        if last < now - timedelta(days=self.last_sale_lookup_days):
            return None
        return last

    @beartype
    def global_sales_cursor(self) -> datetime | None:
        return self.store.load_global_cursor()
