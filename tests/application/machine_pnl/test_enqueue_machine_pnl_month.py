from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.machine_pnl.enqueue import enqueue_machine_period_pnl_jobs
from src.domain.events import DomainEvent
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_pnl.events import MachineMonthPnlRequested

_TECH = TechnicianId("tech-1")
_OPENED = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_LINE = ReconciliationLine(
    product_code="sku-1",
    actual_prev=Decimal("10"),
    actual=Decimal("7"),
    calculated=Decimal("5"),
    delta=Decimal("2"),
    loads_total=Decimal("0"),
    sales_total=Decimal("3"),
)


@dataclass
class _RecordingPublisher:
    events: list[DomainEvent]

    def __init__(self) -> None:
        self.events = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def _snapshot(
    *,
    period_id: str,
    machine_id: str,
    status: str = "complete",
    reconciled: bool = True,
    opened_at: datetime = _OPENED,
    closed_at: datetime = _CLOSED,
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId(machine_id),
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("rev-open"),
        closing_revision_id=RevisionId("rev-close"),
        opened_at=opened_at,
        closed_at=closed_at,
        lines=(_LINE,),
        sales_lines=(),
        load_count=0,
        status=status,  # type: ignore[arg-type]
        reconciled=reconciled,
    )


def test_enqueue_month_jobs_alongside_period() -> None:
    publisher = _RecordingPublisher()
    period_id = "period-cross"
    snapshot = _snapshot(
        period_id=period_id,
        machine_id="101",
        opened_at=datetime(2026, 5, 20, tzinfo=UTC),
        closed_at=datetime(2026, 6, 10, tzinfo=UTC),
    )
    enqueue_machine_period_pnl_jobs(
        period_ids=(period_id,),
        snapshots_by_id={period_id: snapshot},
        source_session_id="session-1",
        publisher=publisher,
    )
    types = [type(e).__name__ for e in publisher.events]
    assert "MachinePeriodPnlRequested" in types
    assert "MachineMonthPnlRequested" in types
    month = next(e for e in publisher.events if isinstance(e, MachineMonthPnlRequested))
    assert month.event_id.value == f"machine_pnl_month:{period_id}"
    assert date(2026, 5, 1) in month.period_start_dates
    assert date(2026, 6, 1) in month.period_start_dates


def test_enqueue_month_skips_snack() -> None:
    publisher = _RecordingPublisher()
    period_id = "snack-1"
    snapshot = _snapshot(period_id=period_id, machine_id="501")
    enqueue_machine_period_pnl_jobs(
        period_ids=(period_id,),
        snapshots_by_id={period_id: snapshot},
        source_session_id="session-skip",
        publisher=publisher,
    )
    assert publisher.events == []
