from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import (
    AccountabilityId,
    EventId,
    MachineId,
    ReconciliationSessionId,
    TechnicianId,
)
from src.domain.technician_settlement.events import (
    PeriodAccountabilityRecorded,
    TechnicianLedgerClearedByReconciliation,
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)


def test_period_accountability_recorded_fields() -> None:
    event = PeriodAccountabilityRecorded(
        event_id=EventId("event-1"),
        accountability_id=AccountabilityId("tech-a:p1"),
        technician_id=TechnicianId("tech-a"),
        period_id="p1",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee": Decimal("-2")},
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 1, 1, tzinfo=UTC),
    )
    assert event.delta_by_sku["coffee"] == Decimal("-2")


def test_session_completed_and_cleared_fields() -> None:
    completed = TechnicianReconciliationSessionCompleted(
        event_id=EventId("event-2"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        mode="inventory_delta",
        anchor_at=datetime(2026, 5, 25, tzinfo=UTC),
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=datetime(2026, 5, 25, tzinfo=UTC),
        warehouse_delta_by_sku={"coffee": Decimal("2")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={"coffee": Decimal("-2")},
        residual_by_sku={},
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    cleared = TechnicianLedgerClearedByReconciliation(
        event_id=EventId("event-3"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        period_ids=("p1",),
        cleared_by_sku={"coffee": Decimal("-2")},
        residual_by_sku={},
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    assert completed.mode == "inventory_delta"
    assert cleared.cleared_by_sku["coffee"] == Decimal("-2")


def test_session_committed_composite_fields() -> None:
    event = TechnicianReconciliationSessionCommitted(
        event_id=EventId("event-committed"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        mode="inventory_delta",
        anchor_at=datetime(2026, 5, 25, tzinfo=UTC),
        period_ids=("p1",),
        deferred_period_ids=("p2",),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=datetime(2026, 5, 25, tzinfo=UTC),
        warehouse_delta_by_sku={"coffee": Decimal("2")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={"coffee": Decimal("-2")},
        cleared_by_sku={"coffee": Decimal("-2")},
        residual_by_sku={},
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    assert event.cleared_by_sku == {"coffee": Decimal("-2")}
    assert event.ledger_balance_before == {"coffee": Decimal("-2")}
    assert event.deferred_period_ids == ("p2",)
