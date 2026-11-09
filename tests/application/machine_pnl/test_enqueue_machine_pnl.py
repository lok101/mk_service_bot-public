from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.machine_pnl.enqueue import enqueue_machine_period_pnl_jobs
from src.application.outbox.handler_ids import MACHINE_PNL_PERIOD_HANDLER_ID
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_pnl.events import MachinePeriodPnlRequested
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher

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


def _snapshot(
    *,
    period_id: str,
    machine_id: str,
    status: str = "complete",
    reconciled: bool = True,
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId(machine_id),
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("rev-open"),
        closing_revision_id=RevisionId("rev-close"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(_LINE,),
        sales_lines=(),
        load_count=0,
        status=status,  # type: ignore[arg-type]
        reconciled=reconciled,
    )


def _publisher_store() -> tuple[OutboxDomainEventPublisher, InMemoryOutboxStore]:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    publisher.subscribe(MachinePeriodPnlRequested, MACHINE_PNL_PERIOD_HANDLER_ID)
    return publisher, store


def test_enqueue_machine_pnl_uses_period_event_id() -> None:
    publisher, store = _publisher_store()
    period_id = "period-1"
    snapshots = {
        period_id: _snapshot(period_id=period_id, machine_id="101"),
    }

    enqueue_machine_period_pnl_jobs(
        period_ids=(period_id,),
        snapshots_by_id=snapshots,
        source_session_id="session-1",
        publisher=publisher,
    )

    captured = list(store._entries.values())
    assert len(captured) == 1
    assert captured[0]["event_id"] == "machine_pnl:period-1"
    assert captured[0]["handler_id"] == "machine_pnl_period"
    assert captured[0]["event_document"]["payload"]["source_session_id"] == "session-1"


def test_enqueue_skips_snack_and_incomplete() -> None:
    publisher, store = _publisher_store()
    snapshots = {
        "snack-1": _snapshot(period_id="snack-1", machine_id="501"),
        "pending-1": _snapshot(
            period_id="pending-1",
            machine_id="101",
            status="pending_sales",
        ),
        "unreconciled-1": _snapshot(
            period_id="unreconciled-1",
            machine_id="101",
            reconciled=False,
        ),
    }

    enqueue_machine_period_pnl_jobs(
        period_ids=("snack-1", "pending-1", "unreconciled-1"),
        snapshots_by_id=snapshots,
        source_session_id="session-skip",
        publisher=publisher,
    )

    assert list(store._entries.values()) == []
