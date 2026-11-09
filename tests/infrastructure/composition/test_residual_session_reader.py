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
from src.infrastructure.composition.adapters.residual_session_reader import (
    SettlementResidualSessionReader,
)
from src.infrastructure.testing.settlement_fakes import (
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)

_ANCHOR = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
_TECH_1 = TechnicianId("tech-1")
_TECH_2 = TechnicianId("tech-2")
_SKU = "coffee-beans"


def _completed_session(
    *,
    event_id: str,
    session_id: str,
    technician_id: TechnicianId,
    mode: str = "inventory_delta",
    period_ids: tuple[str, ...] = ("p1",),
    deferred_period_ids: tuple[str, ...] = (),
    residual_by_sku: dict[str, Decimal] | None = None,
) -> TechnicianReconciliationSessionCompleted:
    if residual_by_sku is None:
        residual_by_sku = {_SKU: Decimal("-5")}
    return TechnicianReconciliationSessionCompleted(
        event_id=EventId(event_id),
        session_id=ReconciliationSessionId(session_id),
        technician_id=technician_id,
        mode=mode,  # type: ignore[arg-type]
        anchor_at=_ANCHOR,
        period_ids=period_ids,
        deferred_period_ids=deferred_period_ids,
        warehouse_inventory_id="warehouse-inv-1",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={_SKU: Decimal("1")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={_SKU: Decimal("-5")},
        residual_by_sku=residual_by_sku,
        finalized_at=_ANCHOR,
        occurred_at=_ANCHOR,
        executed_at=_ANCHOR,
    )


def _repository_with(
    *events: (
        TechnicianReconciliationSessionCompleted
        | TechnicianReconciliationSessionCommitted
        | PeriodAccountabilityRecorded
        | TechnicianLedgerClearedByReconciliation
    ),
) -> InMemoryTechnicianSettlementRepository:
    event_store = InMemoryTechnicianSettlementEventStore()
    versions: dict[str, int] = {}
    for event in events:
        tech = event.technician_id.value
        expected = versions.get(tech, 0)
        event_store.append(
            event,
            expected_version=expected,
        )
        versions[tech] = expected + 1
    return InMemoryTechnicianSettlementRepository(event_store=event_store)


def test_residual_session_reader_matches_period_on_technician_stream() -> None:
    repository = _repository_with(
        _completed_session(
            event_id="evt-1",
            session_id="sess-1",
            technician_id=_TECH_1,
            period_ids=("p1",),
            deferred_period_ids=("def-1",),
            residual_by_sku={_SKU: Decimal("-5")},
        ),
    )
    reader = SettlementResidualSessionReader(repository)

    found = reader.find_completed_containing("p1", technician_id=_TECH_1)

    assert len(found) == 1
    assert found[0].session_id == "sess-1"
    assert found[0].period_ids == ("p1",)
    assert "def-1" not in found[0].period_ids
    assert found[0].technician_id == "tech-1"
    assert found[0].anchor_at == _ANCHOR
    assert found[0].residual_by_sku == {_SKU: Decimal("-5")}


def test_residual_session_reader_includes_exit_mode() -> None:
    repository = _repository_with(
        _completed_session(
            event_id="evt-exit",
            session_id="sess-exit",
            technician_id=_TECH_1,
            mode="exit_warehouse_closed",
            period_ids=("p1",),
            residual_by_sku={_SKU: Decimal("-9")},
        ),
    )
    reader = SettlementResidualSessionReader(repository)

    found = reader.find_completed_containing("p1", technician_id=_TECH_1)

    assert len(found) == 1
    assert found[0].session_id == "sess-exit"
    assert found[0].residual_by_sku == {_SKU: Decimal("-9")}


def test_residual_session_reader_ignores_deferred_and_other_tech() -> None:
    repository = _repository_with(
        _completed_session(
            event_id="evt-deferred-only",
            session_id="sess-def",
            technician_id=_TECH_1,
            period_ids=("other-p",),
            deferred_period_ids=("p1",),
        ),
        _completed_session(
            event_id="evt-other-tech",
            session_id="sess-tech2",
            technician_id=_TECH_2,
            period_ids=("p1",),
        ),
        PeriodAccountabilityRecorded(
            event_id=EventId("evt-accountability"),
            accountability_id=AccountabilityId("tech-1:p1"),
            technician_id=_TECH_1,
            period_id="p1",
            machine_id=MachineId("101"),
            delta_by_sku={_SKU: Decimal("-1")},
            closed_at=_ANCHOR,
            occurred_at=_ANCHOR,
        ),
        TechnicianLedgerClearedByReconciliation(
            event_id=EventId("evt-cleared"),
            session_id=ReconciliationSessionId("sess-cleared"),
            technician_id=_TECH_1,
            period_ids=("p1",),
            cleared_by_sku={_SKU: Decimal("1")},
            residual_by_sku={_SKU: Decimal("-1")},
            occurred_at=_ANCHOR,
        ),
    )
    reader = SettlementResidualSessionReader(repository)

    found = reader.find_completed_containing("p1", technician_id=_TECH_1)

    assert found == ()


def test_residual_reader_reads_new_composite_and_legacy_completed() -> None:
    committed = TechnicianReconciliationSessionCommitted(
        event_id=EventId("evt-committed"),
        session_id=ReconciliationSessionId("sess-committed"),
        technician_id=_TECH_1,
        mode="inventory_delta",
        anchor_at=_ANCHOR,
        period_ids=("p1",),
        deferred_period_ids=(),
        warehouse_inventory_id="warehouse-inv-1",
        warehouse_inventory_moment=_ANCHOR,
        warehouse_delta_by_sku={_SKU: Decimal("1")},
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={_SKU: Decimal("-5")},
        cleared_by_sku={_SKU: Decimal("-5")},
        residual_by_sku={_SKU: Decimal("-2")},
        finalized_at=_ANCHOR,
        executed_at=_ANCHOR,
        occurred_at=_ANCHOR,
    )
    repository = _repository_with(
        _completed_session(
            event_id="evt-legacy",
            session_id="sess-legacy",
            technician_id=_TECH_1,
            period_ids=("p1",),
            residual_by_sku={_SKU: Decimal("-5")},
        ),
        committed,
    )
    reader = SettlementResidualSessionReader(repository)
    found = reader.find_completed_containing("p1", technician_id=_TECH_1)
    assert {view.session_id for view in found} == {"sess-legacy", "sess-committed"}
