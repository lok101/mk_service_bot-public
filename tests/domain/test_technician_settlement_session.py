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
from src.domain.technician_settlement.aggregate import (
    CompleteReconciliationSession,
    RecordPeriodAccountability,
    TechnicianSettlement,
)
from src.domain.technician_settlement.events import (
    PeriodAccountabilityRecorded,
    TechnicianLedgerClearedByReconciliation,
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
    WarehouseTransferRef,
)

_ANCHOR = datetime(2026, 5, 25, tzinfo=UTC)


def _seed() -> TechnicianSettlement:
    aggregate = TechnicianSettlement.empty(TechnicianId("tech-a"))
    aggregate.record_period_accountability(
        RecordPeriodAccountability(
            accountability_id=AccountabilityId("tech-a:p1"),
            period_id="p1",
            machine_id=MachineId("vm-01"),
            delta_by_sku={"coffee": Decimal("-1000")},
            closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        ),
    )
    aggregate.clear_pending_events()
    return aggregate


def _command(residual: dict[str, Decimal]) -> CompleteReconciliationSession:
    return CompleteReconciliationSession(
        session_id=ReconciliationSessionId("sess-1"),
        mode="inventory_delta",
        anchor_at=_ANCHOR,
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={"coffee": Decimal("1000")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={"coffee": Decimal("-1000")},
        residual_by_sku=residual,
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )


def _complete_regular_session() -> TechnicianReconciliationSessionCompleted:
    return TechnicianReconciliationSessionCompleted(
        event_id=EventId("event-regular"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        mode="inventory_delta",
        anchor_at=_ANCHOR,
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={"coffee": Decimal("1000")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={"coffee": Decimal("-1000")},
        residual_by_sku={},
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )


def _complete_exit_warehouse_closed_session() -> TechnicianReconciliationSessionCompleted:
    return TechnicianReconciliationSessionCompleted(
        event_id=EventId("event-exit"),
        session_id=ReconciliationSessionId("sess-exit"),
        technician_id=TechnicianId("tech-a"),
        mode="exit_warehouse_closed",
        anchor_at=_ANCHOR,
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="exit-evt-1",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={"coffee": Decimal("-1")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={"coffee": Decimal("-1000")},
        residual_by_sku={"coffee": Decimal("-1001")},
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )


def test_completed_session_uses_neutral_warehouse_fields() -> None:
    event = _complete_regular_session()
    assert event.warehouse_inventory_id == "warehouse-inv-2"
    assert event.warehouse_inventory_moment == _ANCHOR
    assert event.warehouse_delta_by_sku == {"coffee": Decimal("1000")}
    assert event.warehouse_source == "domain_technician_warehouse"
    assert not hasattr(event, "ms_inventory_id")
    assert not hasattr(event, "inv_delta_by_sku")


def test_reconciliation_mode_literal_excludes_termination() -> None:
    from typing import get_args

    from src.domain.technician_settlement.events import ReconciliationMode

    assert set(get_args(ReconciliationMode)) == {
        "inventory_delta",
        "exit_warehouse_closed",
    }


def test_exit_warehouse_closed_session_stores_mode() -> None:
    event = _complete_exit_warehouse_closed_session()
    assert event.mode == "exit_warehouse_closed"
    assert event.warehouse_inventory_id == "exit-evt-1"
    assert event.warehouse_delta_by_sku == {"coffee": Decimal("-1")}
    assert event.deferred_period_ids == ()


def test_complete_session_emits_one_composite_event_and_clears_ledger() -> None:
    aggregate = _seed()
    result = aggregate.complete_reconciliation_session(_command({}))
    events = aggregate.collect_events()
    assert events == [result.committed_event]
    assert isinstance(result.committed_event, TechnicianReconciliationSessionCommitted)
    assert result.cleared_by_sku == {"coffee": Decimal("-1000")}
    assert result.session_id == ReconciliationSessionId("sess-1")
    assert result.residual_by_sku == {}
    assert aggregate.net_balance_by_sku()["coffee"] == Decimal("0")
    assert aggregate.last_session_finalized_at() == datetime(2026, 5, 25, 1, tzinfo=UTC)


def test_duplicate_session_returns_same_normalized_result_without_new_event() -> None:
    aggregate = _seed()
    first = aggregate.complete_reconciliation_session(_command({}))
    second = aggregate.complete_reconciliation_session(_command({}))
    assert second.committed_event.event_id == first.committed_event.event_id
    assert second.session_id == first.session_id
    assert second.cleared_by_sku == first.cleared_by_sku
    assert len(aggregate.collect_events()) == 1
    assert aggregate.net_balance_by_sku()["coffee"] == Decimal("0")


def test_complete_session_idempotent_after_rehydrate() -> None:
    aggregate = TechnicianSettlement.empty(TechnicianId("tech-a"))
    accountability = aggregate.record_period_accountability(
        RecordPeriodAccountability(
            accountability_id=AccountabilityId("tech-a:p1"),
            period_id="p1",
            machine_id=MachineId("vm-01"),
            delta_by_sku={"coffee": Decimal("-1000")},
            closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        ),
    )
    assert accountability is not None
    aggregate.clear_pending_events()
    first = aggregate.complete_reconciliation_session(_command({}))
    aggregate.clear_pending_events()
    replayed = TechnicianSettlement.rehydrate(
        aggregate.technician_id,
        [accountability, first.committed_event],
    )
    second = replayed.complete_reconciliation_session(_command({}))
    assert second.committed_event.event_id == first.committed_event.event_id
    assert replayed.collect_events() == []
    assert replayed.net_balance_by_sku()["coffee"] == Decimal("0")


def test_complete_session_persists_transfer_refs() -> None:
    aggregate = _seed()
    command = CompleteReconciliationSession(
        session_id=ReconciliationSessionId("sess-2"),
        mode="inventory_delta",
        anchor_at=_ANCHOR,
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="warehouse-inv-2",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={"coffee": Decimal("1000")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(WarehouseTransferRef("move-1", "hash-1"),),
        ledger_balance_before={"coffee": Decimal("-1000")},
        residual_by_sku={},
        finalized_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
        executed_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    result = aggregate.complete_reconciliation_session(command)
    assert result.committed_event.warehouse_transfer_refs == (
        WarehouseTransferRef("move-1", "hash-1"),
    )


def _accountability() -> PeriodAccountabilityRecorded:
    return PeriodAccountabilityRecorded(
        event_id=EventId("event-acc"),
        accountability_id=AccountabilityId("tech-a:p1"),
        technician_id=TechnicianId("tech-a"),
        period_id="p1",
        machine_id=MachineId("vm-01"),
        delta_by_sku={"coffee": Decimal("-1000")},
        closed_at=datetime(2026, 5, 1, tzinfo=UTC),
        occurred_at=datetime(2026, 5, 1, 1, tzinfo=UTC),
    )


def test_legacy_completed_and_cleared_pair_rehydrates_same_normalized_result() -> None:
    completed = _complete_regular_session()
    cleared = TechnicianLedgerClearedByReconciliation(
        event_id=EventId("event-cleared"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        period_ids=("p1",),
        cleared_by_sku={"coffee": Decimal("-1000")},
        residual_by_sku={},
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    aggregate = TechnicianSettlement.rehydrate(
        TechnicianId("tech-a"),
        [_accountability(), completed, cleared],
    )
    result = aggregate.completion_result_for(ReconciliationSessionId("sess-1"))
    assert result is not None
    assert isinstance(result.committed_event, TechnicianReconciliationSessionCommitted)
    assert result.cleared_by_sku == {"coffee": Decimal("-1000")}
    assert result.session_id == ReconciliationSessionId("sess-1")
    assert aggregate.net_balance_by_sku()["coffee"] == Decimal("0")
    assert aggregate.last_session_finalized_at() == completed.finalized_at


def test_legacy_completed_without_clear_is_not_reported_as_committed() -> None:
    completed = _complete_regular_session()
    aggregate = TechnicianSettlement.rehydrate(
        TechnicianId("tech-a"),
        [_accountability(), completed],
    )
    assert aggregate.completion_result_for(ReconciliationSessionId("sess-1")) is None
    assert aggregate.net_balance_by_sku() == {"coffee": Decimal("-1000")}
    assert aggregate.last_session_finalized_at() is None

    result = aggregate.complete_reconciliation_session(_command({}))
    assert isinstance(result.committed_event, TechnicianReconciliationSessionCommitted)
    assert len(aggregate.collect_events()) == 1
    assert aggregate.net_balance_by_sku()["coffee"] == Decimal("0")


def test_new_composite_and_legacy_pair_produce_same_observable_state() -> None:
    accountability = _accountability()
    composite_live = TechnicianSettlement.rehydrate(TechnicianId("tech-a"), [accountability])
    composite_result = composite_live.complete_reconciliation_session(_command({}))
    composite = TechnicianSettlement.rehydrate(
        TechnicianId("tech-a"),
        [accountability, composite_result.committed_event],
    )

    completed = _complete_regular_session()
    cleared = TechnicianLedgerClearedByReconciliation(
        event_id=EventId("event-cleared"),
        session_id=ReconciliationSessionId("sess-1"),
        technician_id=TechnicianId("tech-a"),
        period_ids=("p1",),
        cleared_by_sku={"coffee": Decimal("-1000")},
        residual_by_sku={},
        occurred_at=datetime(2026, 5, 25, 1, tzinfo=UTC),
    )
    legacy = TechnicianSettlement.rehydrate(
        TechnicianId("tech-a"),
        [accountability, completed, cleared],
    )

    assert composite.net_balance_by_sku() == legacy.net_balance_by_sku()
    assert composite.last_session_finalized_at() == legacy.last_session_finalized_at()
    composite_view = composite.completion_result_for(ReconciliationSessionId("sess-1"))
    legacy_view = legacy.completion_result_for(ReconciliationSessionId("sess-1"))
    assert composite_view is not None
    assert legacy_view is not None
    assert composite_view.session_id == legacy_view.session_id
    assert composite_view.cleared_by_sku == legacy_view.cleared_by_sku
    assert composite_view.residual_by_sku == legacy_view.residual_by_sku
    assert composite_view.mode == legacy_view.mode
    assert composite_view.period_ids == legacy_view.period_ids
    assert composite_view.warehouse_inventory_id == legacy_view.warehouse_inventory_id
    assert composite_view.warehouse_source == legacy_view.warehouse_source
