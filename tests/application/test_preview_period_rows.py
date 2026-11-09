from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.application.technician_settlement.preview_period_rows import (
    build_reconciliation_period_rows,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


def _snapshot(
    *,
    period_id: str,
    machine_id: MachineId,
    opened_at: datetime,
    location_name: str,
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=machine_id,
        responsible_technician_id=TechnicianId("10003"),
        opening_revision_id=RevisionId(f"open-{period_id}"),
        closing_revision_id=RevisionId(f"close-{period_id}"),
        opened_at=opened_at,
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        lines=(),
        sales_lines=(),
        load_count=0,
        status="complete",
        location_name=location_name,
        technician_name="Frozen Tech",
    )


def test_build_reconciliation_period_rows_uses_snapshot_location_name() -> None:
    # Live Sheets would differ; sort + display use snapshot.location_name.
    same_opened = datetime(2026, 5, 1, tzinfo=UTC)
    snap_z = _snapshot(
        period_id="p-z",
        machine_id=MachineId("vm-z"),
        opened_at=same_opened,
        location_name="Frozen Z",
    )
    snap_a = _snapshot(
        period_id="p-a",
        machine_id=MachineId("vm-a"),
        opened_at=same_opened,
        location_name="Frozen A",
    )
    rows = build_reconciliation_period_rows(
        periods=(snap_z, snap_a),
        tz=ZoneInfo("UTC"),
    )
    assert rows[0].machine_name == "Frozen A"
    assert rows[1].machine_name == "Frozen Z"
