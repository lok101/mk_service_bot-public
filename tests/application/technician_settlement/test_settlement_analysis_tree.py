from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.technician_settlement.settlement_analysis import (
    BuildSettlementAnalysisTree,
)
from src.domain.ids import (
    AccountabilityId,
    EventId,
    MachineId,
    ReconciliationSessionId,
    RevisionId,
    TechnicianId,
)
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement.events import (
    PeriodAccountabilityRecorded,
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
)
from src.infrastructure.testing.settlement_fakes import (
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
)

_TECH = TechnicianId("10015")


def _completed(
    *,
    session_id: str,
    mode: str,
    period_ids: tuple[str, ...],
    residual: dict[str, Decimal],
    warehouse_delta: dict[str, Decimal] | None = None,
    technician_id: str = "10015",
    inventory_moment: datetime | None = None,
    finalized_at: datetime | None = None,
) -> TechnicianReconciliationSessionCompleted:
    now = inventory_moment or datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    done = finalized_at or now
    return TechnicianReconciliationSessionCompleted(
        event_id=EventId(f"event-{session_id}"),
        session_id=ReconciliationSessionId(session_id),
        technician_id=TechnicianId(technician_id),
        mode=mode,  # type: ignore[arg-type]
        anchor_at=now,
        period_ids=period_ids,
        deferred_period_ids=(),
        warehouse_inventory_id=f"inv-{session_id}",
        warehouse_inventory_moment=now,
        warehouse_delta_by_sku=dict(warehouse_delta or {}),
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before={},
        residual_by_sku=dict(residual),
        finalized_at=done,
        occurred_at=done,
        executed_at=done,
    )


def _committed(
    *,
    session_id: str,
    mode: str,
    period_ids: tuple[str, ...],
    residual: dict[str, Decimal],
    warehouse_delta: dict[str, Decimal] | None = None,
    technician_id: str = "10015",
    inventory_moment: datetime | None = None,
    finalized_at: datetime | None = None,
) -> TechnicianReconciliationSessionCommitted:
    now = inventory_moment or datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    done = finalized_at or now
    cleared = dict(residual)
    return TechnicianReconciliationSessionCommitted(
        event_id=EventId(f"event-{session_id}"),
        session_id=ReconciliationSessionId(session_id),
        technician_id=TechnicianId(technician_id),
        mode=mode,  # type: ignore[arg-type]
        anchor_at=now,
        period_ids=period_ids,
        deferred_period_ids=(),
        warehouse_inventory_id=f"inv-{session_id}",
        warehouse_inventory_moment=now,
        warehouse_delta_by_sku=dict(warehouse_delta or {}),
        warehouse_source="domain_technician_warehouse",
        warehouse_transfer_refs=(),
        ledger_balance_before=dict(cleared),
        cleared_by_sku=dict(cleared),
        residual_by_sku=dict(residual),
        finalized_at=done,
        occurred_at=done,
        executed_at=done,
    )


def _snapshot(
    period_id: str,
    *,
    location_name: str = "Loc A",
    opened_at: datetime | None = None,
    closed_at: datetime | None = None,
    sales: dict[str, Decimal] | None = None,
) -> ResponsibilityPeriodReconciliation:
    opened = opened_at or datetime(2026, 7, 1, 8, 0, tzinfo=UTC)
    closed = closed_at or datetime(2026, 7, 7, 18, 0, tzinfo=UTC)
    lines = tuple(
        ReconciliationLine(
            product_code=code,
            actual_prev=Decimal("0"),
            actual=Decimal("0"),
            calculated=Decimal("0"),
            delta=Decimal("0"),
            sales_total=qty,
        )
        for code, qty in (sales or {}).items()
    )
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId(f"open-{period_id}"),
        closing_revision_id=RevisionId(f"close-{period_id}"),
        opened_at=opened,
        closed_at=closed,
        lines=lines,
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=True,
        location_name=location_name,
    )


def test_tree_lists_new_composite_committed_session() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    moment = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    events.append(
        _committed(
            session_id="sess-new",
            mode="inventory_delta",
            period_ids=("p-new",),
            residual={"COFFEE": Decimal("-4")},
            inventory_moment=moment,
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p-new", location_name="New Cafe"))

    tree = BuildSettlementAnalysisTree(events, snapshots).execute(_TECH)

    assert len(tree.clusters) == 1
    assert tree.clusters[0].session_id == "sess-new"
    assert tree.clusters[0].mode == "inventory_delta"
    assert tree.clusters[0].warehouse_inventory_moment == moment
    assert tree.clusters[0].periods[0].period_id == "p-new"


def test_tree_lists_legacy_completed_and_new_committed() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    older = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    newer = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    events.append(
        _completed(
            session_id="sess-legacy",
            mode="inventory_delta",
            period_ids=("p-legacy",),
            residual={"COFFEE": Decimal("-1")},
            inventory_moment=older,
        ),
        expected_version=0,
    )
    events.append(
        _committed(
            session_id="sess-composite",
            mode="exit_warehouse_closed",
            period_ids=("p-composite",),
            residual={"COFFEE": Decimal("-2")},
            inventory_moment=newer,
        ),
        expected_version=1,
    )
    snapshots.save(_snapshot("p-legacy", location_name="Legacy"))
    snapshots.save(_snapshot("p-composite", location_name="Composite"))

    tree = BuildSettlementAnalysisTree(events, snapshots).execute(_TECH)

    assert len(tree.clusters) == 2
    assert tree.clusters[0].session_id == "sess-composite"
    assert tree.clusters[0].mode == "exit_warehouse_closed"
    assert tree.clusters[1].session_id == "sess-legacy"
    assert tree.clusters[1].mode == "inventory_delta"


def test_tree_lists_completed_inventory_and_exit() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    older = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    newer = datetime(2026, 8, 10, 10, 0, tzinfo=UTC)
    events.append(
        _completed(
            session_id="sess-inv",
            mode="inventory_delta",
            period_ids=("p-inv",),
            residual={"COFFEE": Decimal("-1")},
            inventory_moment=older,
        ),
        expected_version=0,
    )
    events.append(
        _completed(
            session_id="sess-exit",
            mode="exit_warehouse_closed",
            period_ids=("p-exit",),
            residual={"COFFEE": Decimal("-2")},
            inventory_moment=newer,
        ),
        expected_version=1,
    )
    snapshots.save(_snapshot("p-inv", location_name="Cafe"))
    snapshots.save(_snapshot("p-exit", location_name="Office"))

    tree = BuildSettlementAnalysisTree(events, snapshots).execute(_TECH)

    assert len(tree.clusters) == 2
    assert tree.clusters[0].session_id == "sess-exit"
    assert tree.clusters[0].mode == "exit_warehouse_closed"
    assert tree.clusters[1].session_id == "sess-inv"
    assert tree.clusters[1].mode == "inventory_delta"


def test_tree_excludes_non_completed() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    events.append(
        PeriodAccountabilityRecorded(
            event_id=EventId("acc-1"),
            accountability_id=AccountabilityId("acc-1"),
            technician_id=_TECH,
            period_id="p-only",
            machine_id=MachineId("vm-01"),
            delta_by_sku={"COFFEE": Decimal("-5")},
            closed_at=now,
            occurred_at=now,
        ),
        expected_version=0,
    )

    tree = BuildSettlementAnalysisTree(events, snapshots).execute(_TECH)

    assert tree.clusters == ()


def test_tree_period_row_from_snapshot() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    opened = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    closed = datetime(2026, 6, 8, 17, 0, tzinfo=UTC)
    events.append(
        _completed(
            session_id="sess-1",
            mode="inventory_delta",
            period_ids=("p-1",),
            residual={},
        ),
        expected_version=0,
    )
    snapshots.save(
        _snapshot(
            "p-1",
            location_name="Market",
            opened_at=opened,
            closed_at=closed,
        )
    )

    tree = BuildSettlementAnalysisTree(events, snapshots).execute(_TECH)

    assert len(tree.clusters) == 1
    row = tree.clusters[0].periods[0]
    assert row.period_id == "p-1"
    assert row.location_name == "Market"
    assert row.opened_at == opened
    assert row.closed_at == closed
    assert row.missing_snapshot is False


def test_tree_sorts_periods_by_location_then_opened_at() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    older = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    mid = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    newer = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    events.append(
        _completed(
            session_id="sess-order",
            mode="inventory_delta",
            period_ids=("p-b-new", "p-missing", "p-a-old", "p-a-mid"),
            residual={},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p-b-new", location_name="Б Локация", opened_at=newer))
    snapshots.save(_snapshot("p-a-old", location_name="А Локация", opened_at=older))
    snapshots.save(_snapshot("p-a-mid", location_name="А Локация", opened_at=mid))

    tree = BuildSettlementAnalysisTree(events, snapshots).execute(_TECH)

    period_ids = tuple(row.period_id for row in tree.clusters[0].periods)
    assert period_ids == ("p-a-old", "p-a-mid", "p-b-new", "p-missing")
    assert tree.clusters[0].periods[3].missing_snapshot is True


def test_tree_missing_snapshot_flagged() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="sess-miss",
            mode="inventory_delta",
            period_ids=("p-missing",),
            residual={},
        ),
        expected_version=0,
    )

    tree = BuildSettlementAnalysisTree(events, snapshots).execute(_TECH)

    assert len(tree.clusters) == 1
    row = tree.clusters[0].periods[0]
    assert row.period_id == "p-missing"
    assert row.missing_snapshot is True


class _LiveLocationLookup:
    def location_name(self, machine_id: MachineId) -> str | None:
        if machine_id.value == "vm-01":
            return "БЦ Белинского | Белинского, 34"
        return None

    def technician_name(self, technician_id: TechnicianId) -> str | None:
        return None


def test_tree_fills_location_name_from_lookup_when_snapshot_blank() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="sess-blank",
            mode="inventory_delta",
            period_ids=("p-blank",),
            residual={},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p-blank", location_name=""))

    tree = BuildSettlementAnalysisTree(
        events,
        snapshots,
        party_names_lookup=_LiveLocationLookup(),
    ).execute(_TECH)

    assert tree.clusters[0].periods[0].location_name == "БЦ Белинского | Белинского, 34"


def test_tree_keeps_frozen_location_name() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="sess-frozen",
            mode="inventory_delta",
            period_ids=("p-frozen",),
            residual={},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p-frozen", location_name="Лыжная база JL300 | Алексея Стаханова, 65"))

    tree = BuildSettlementAnalysisTree(
        events,
        snapshots,
        party_names_lookup=_LiveLocationLookup(),
    ).execute(_TECH)

    assert tree.clusters[0].periods[0].location_name == "Лыжная база JL300 | Алексея Стаханова, 65"
