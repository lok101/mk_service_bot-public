from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.technician_settlement.audit_format import format_audit_datetime
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationPeriodRow:
    machine_name: str
    opened_at: str
    closed_at: str


@beartype
def build_reconciliation_period_rows(
    *,
    periods: tuple[ResponsibilityPeriodReconciliation, ...],
    tz: ZoneInfo,
) -> tuple[ReconciliationPeriodRow, ...]:
    sorted_periods = sorted(
        periods,
        key=lambda snapshot: (
            snapshot.opened_at,
            snapshot.location_name,
        ),
    )
    return tuple(
        ReconciliationPeriodRow(
            machine_name=snapshot.location_name,
            opened_at=format_audit_datetime(snapshot.opened_at, tz),
            closed_at=format_audit_datetime(snapshot.closed_at, tz),
        )
        for snapshot in sorted_periods
    )
