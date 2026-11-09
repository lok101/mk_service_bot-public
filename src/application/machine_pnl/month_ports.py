from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation import MachineCompanyOccupancy
from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.domain.ids import MachineId


@runtime_checkable
class MonthPnlSnapshotStore(Protocol):
    @beartype
    def upsert(self, snapshot: MonthPnlSnapshot) -> None: ...

    @beartype
    def get(self, machine_id: MachineId, period_start: date) -> MonthPnlSnapshot | None: ...

    @beartype
    def list_for_period_starts(
        self,
        period_starts: Sequence[date],
    ) -> tuple[MonthPnlSnapshot, ...]: ...


@runtime_checkable
class MachineCompanyOccupancyReader(Protocol):
    @beartype
    def list_for_machine(
        self,
        machine_id: MachineId,
    ) -> tuple[MachineCompanyOccupancy, ...]: ...
