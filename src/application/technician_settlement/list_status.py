from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.machine_operations.ports import VendingMachineRepository
from src.application.shared.display_names import technician_display_name
from src.application.technician_warehouse.ports import (
    TechnicianWarehouseEventStore,
    TechnicianWarehouseRepository,
)

__all__ = [
    "ListTechnicianSettlementStatus",
    "SettlementStatusReport",
    "SettlementStatusRow",
]

_MISSING_TECHNICIAN_NAME = "не найден в таблице"


@beartype
@dataclass(frozen=True, slots=True)
class SettlementStatusRow:
    technician_id: str
    technician_label: str
    warehouse_open: bool
    unreconciled_count: int
    oldest_opened_at: datetime | None


@beartype
@dataclass(frozen=True, slots=True)
class SettlementStatusReport:
    rows: tuple[SettlementStatusRow, ...]


@beartype
@dataclass(frozen=True, slots=True)
class ListTechnicianSettlementStatus:
    warehouse_event_store: TechnicianWarehouseEventStore
    warehouse_repository: TechnicianWarehouseRepository
    period_repository: ResponsibilityPeriodReconciliationRepository
    machines: VendingMachineRepository

    @beartype
    def execute(self) -> SettlementStatusReport:
        open_ids = {
            technician_id
            for technician_id in self.warehouse_event_store.list_technician_ids()
            if not self.warehouse_repository.get(technician_id).is_closed()
        }
        unreconciled_ids = set(self.period_repository.list_unreconciled_technician_ids())
        union_ids = open_ids | unreconciled_ids
        rows: list[SettlementStatusRow] = []
        for technician_id in union_ids:
            warehouse_open = not self.warehouse_repository.get(technician_id).is_closed()
            periods = self.period_repository.list_posted_unreconciled(
                technician_id=technician_id,
            )
            oldest = min((period.opened_at for period in periods), default=None)
            name = technician_display_name(
                self.machines,
                technician_id,
                fallback="",
            )
            if not name:
                name = _MISSING_TECHNICIAN_NAME
            rows.append(
                SettlementStatusRow(
                    technician_id=technician_id.value,
                    technician_label=f"{name} ({technician_id.value})",
                    warehouse_open=warehouse_open,
                    unreconciled_count=len(periods),
                    oldest_opened_at=oldest,
                )
            )
        rows.sort(
            key=lambda row: (
                row.warehouse_open,
                row.oldest_opened_at is None,
                row.oldest_opened_at or datetime.min.replace(tzinfo=UTC),
                row.technician_id,
            ),
        )
        return SettlementStatusReport(rows=tuple(rows))
