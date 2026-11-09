from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.inventory_reconciliation.ports import (
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.machine_operations.ports import (
    MachineOperationsRepository,
    VendingMachineRepository,
)
from src.application.shared.display_names import (
    machine_display_name,
    technician_display_name,
    technician_display_name_for_machine,
)
from src.application.technician_settlement.audit_format import format_audit_datetime
from src.application.technician_settlement.pending_sales import (
    pending_sales_snapshots_for_technician,
)
from src.domain.ids import MachineId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation

ASSIGNED_TECHNICIAN_MISSING = "не найден в таблице"


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationBlockerRow:
    machine_name: str
    opened_at: str
    assigned_technician: str
    status: str


@beartype
@dataclass(frozen=True, slots=True)
class ListTechnicianReconciliationBlockersResult:
    technician_id: TechnicianId
    technician_name: str
    pending_sales: tuple[ReconciliationBlockerRow, ...]
    operational_open: tuple[ReconciliationBlockerRow, ...]


@beartype
@dataclass(frozen=True, slots=True)
class ListTechnicianReconciliationBlockers:
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    machines: VendingMachineRepository
    machine_operations: MachineOperationsRepository
    audit_timezone: ZoneInfo

    @beartype
    def execute(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime | None = None,
    ) -> ListTechnicianReconciliationBlockersResult:
        snapshot_at = checked_at or datetime.now(tz=UTC)
        technician_name = technician_display_name(
            self.machines,
            technician_id,
            fallback="",
        )
        pending_snapshots = pending_sales_snapshots_for_technician(
            self.reconciliation_repo,
            technician_id,
        )
        pending_rows = self._build_pending_sales_rows(pending_snapshots)
        pending_machine_ids = frozenset(snapshot.machine_id for snapshot in pending_snapshots)
        operational_rows = self._build_operational_open(
            technician_id,
            checked_at=snapshot_at,
            pending_machine_ids=pending_machine_ids,
        )
        return ListTechnicianReconciliationBlockersResult(
            technician_id=technician_id,
            technician_name=technician_name,
            pending_sales=pending_rows,
            operational_open=operational_rows,
        )

    @beartype
    def _build_pending_sales_rows(
        self,
        snapshots: list[ResponsibilityPeriodReconciliation],
    ) -> tuple[ReconciliationBlockerRow, ...]:
        snapshots_sorted = sorted(
            snapshots,
            key=lambda item: (
                item.opened_at,
                item.location_name,
            ),
        )
        rows = [
            ReconciliationBlockerRow(
                machine_name=snapshot.location_name,
                opened_at=format_audit_datetime(snapshot.opened_at, self.audit_timezone),
                assigned_technician=snapshot.technician_name,
                status="pending_sales",
            )
            for snapshot in snapshots_sorted
        ]
        return tuple(rows)

    @beartype
    def _build_operational_open(
        self,
        technician_id: TechnicianId,
        *,
        checked_at: datetime,
        pending_machine_ids: frozenset[MachineId],
    ) -> tuple[ReconciliationBlockerRow, ...]:
        row_candidates: list[tuple[datetime, str, ReconciliationBlockerRow]] = []
        for machine in self.machines.list_all():
            if machine.id in pending_machine_ids:
                continue
            aggregate = self.machine_operations.get(machine.id)
            phase = aggregate.responsibility_phase(technician_id, checked_at=checked_at)
            if phase == "responsible":
                status = "operational_open"
            else:
                if aggregate.last_revision_opened_by() != technician_id:
                    continue
                revision_id = aggregate.last_revision_id()
                if revision_id is None:
                    continue
                existing = self.reconciliation_repo.get_by_opening_revision(
                    machine.id,
                    revision_id,
                )
                if existing is not None:
                    continue
                status = "expired_unclosed"
            opened_at_raw = aggregate.last_revision_opened_at()
            if opened_at_raw is None:
                continue
            machine_name = machine_display_name(
                self.machines,
                machine.id,
                missing="empty",
            )
            row_candidates.append(
                (
                    opened_at_raw,
                    machine_name,
                    ReconciliationBlockerRow(
                        machine_name=machine_name,
                        opened_at=format_audit_datetime(opened_at_raw, self.audit_timezone),
                        assigned_technician=technician_display_name_for_machine(
                            self.machines,
                            machine.id,
                            fallback=ASSIGNED_TECHNICIAN_MISSING,
                        ),
                        status=status,
                    ),
                ),
            )
        row_candidates.sort(key=lambda item: (item[0], item[1]))
        return tuple(row for _, _, row in row_candidates)
