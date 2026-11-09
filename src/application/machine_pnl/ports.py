from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.machine_pnl.models import PeriodPnl
from src.domain.ids import MachineId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale


@runtime_checkable
class UnitCostCatalog(Protocol):
    @beartype
    def get(self, product_code: str, *, as_of: date) -> Decimal | None: ...


@runtime_checkable
class PeriodPnlStore(Protocol):
    @beartype
    def save(self, pnl: PeriodPnl, *, source_session_id: str | None) -> None: ...

    @beartype
    def get(self, pnl_id: str) -> PeriodPnl | None: ...

    @beartype
    def list_by_period_id(self, period_id: str) -> tuple[PeriodPnl, ...]: ...

    @beartype
    def list_overlapping(
        self,
        machine_id: MachineId,
        *,
        range_start: datetime,
        range_end: datetime,
    ) -> tuple[PeriodPnl, ...]: ...

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[PeriodPnl, ...]: ...


@runtime_checkable
class PeriodSnapshotReader(Protocol):
    """Thin read port; satisfied by ResponsibilityPeriodReconciliationRepository."""

    @beartype
    def get_by_period_id(
        self,
        period_id: str,
    ) -> ResponsibilityPeriodReconciliation | None: ...


@beartype
def as_period_snapshot_reader(
    repo: ResponsibilityPeriodReconciliationRepository,
) -> PeriodSnapshotReader:
    """Narrow a period reconciliation repository to the PnL read port (structural)."""
    return repo


@runtime_checkable
class MachineSalesWindowReader(Protocol):
    """Thin read port; satisfied by MachineSalesStore."""

    @beartype
    def find_in_window(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]: ...
