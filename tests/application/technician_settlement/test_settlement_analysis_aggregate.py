from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.technician_settlement.analysis_prefs import SettlementAnalysisPrefs
from src.application.technician_settlement.settlement_analysis import (
    AggregateSettlementClusters,
    UnknownAnalysisSession,
    format_analysis_rubles,
)
from src.domain.ids import (
    EventId,
    MachineId,
    ReconciliationSessionId,
    RevisionId,
    TechnicianId,
)
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.technician_settlement.events import (
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
) -> TechnicianReconciliationSessionCompleted:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
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
        finalized_at=now,
        occurred_at=now,
        executed_at=now,
    )


def _committed(
    *,
    session_id: str,
    mode: str,
    period_ids: tuple[str, ...],
    residual: dict[str, Decimal],
    warehouse_delta: dict[str, Decimal] | None = None,
    technician_id: str = "10015",
) -> TechnicianReconciliationSessionCommitted:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
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
        finalized_at=now,
        occurred_at=now,
        executed_at=now,
    )


def _snapshot(
    period_id: str,
    *,
    sales: dict[str, Decimal],
) -> ResponsibilityPeriodReconciliation:
    lines = tuple(
        ReconciliationLine(
            product_code=code,
            actual_prev=Decimal("0"),
            actual=Decimal("0"),
            calculated=Decimal("0"),
            delta=Decimal("0"),
            sales_total=qty,
        )
        for code, qty in sales.items()
    )
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId("vm-01"),
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId(f"open-{period_id}"),
        closing_revision_id=RevisionId(f"close-{period_id}"),
        opened_at=datetime(2026, 7, 1, 8, 0, tzinfo=UTC),
        closed_at=datetime(2026, 7, 7, 18, 0, tzinfo=UTC),
        lines=lines,
        sales_lines=(),
        load_count=0,
        status="complete",
        ledger_posted=True,
        location_name="Loc",
    )


def _prefs(
    *,
    prices: dict[str, Decimal] | None = None,
    recoverable: frozenset[str] | None = None,
    n: Decimal = Decimal("2"),
) -> SettlementAnalysisPrefs:
    return SettlementAnalysisPrefs(
        unit_prices=dict(prices or {}),
        recoverable_product_codes=recoverable or frozenset(),
        allowed_loss_pct=n,
    )


def test_aggregate_sums_residual_from_committed_session() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _committed(
            session_id="s-committed",
            mode="inventory_delta",
            period_ids=("p-committed",),
            residual={"COFFEE": Decimal("-7")},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p-committed", sales={"COFFEE": Decimal("70")}))

    result = AggregateSettlementClusters(events, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s-committed"}),
        prefs=_prefs(prices={"COFFEE": Decimal("1")}),
    )

    coffee = next(row for row in result.rows if row.product_code == "COFFEE")
    assert coffee.residual == Decimal("-7")
    assert coffee.consumption == Decimal("70")


def test_aggregate_sums_residual_and_sales_total() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="s1",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-5")},
        ),
        expected_version=0,
    )
    events.append(
        _completed(
            session_id="s2",
            mode="inventory_delta",
            period_ids=("p2",),
            residual={"COFFEE": Decimal("-3")},
        ),
        expected_version=1,
    )
    snapshots.save(_snapshot("p1", sales={"COFFEE": Decimal("100")}))
    snapshots.save(_snapshot("p2", sales={"COFFEE": Decimal("50")}))

    result = AggregateSettlementClusters(events, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s1", "s2"}),
        prefs=_prefs(prices={"COFFEE": Decimal("1")}),
    )

    coffee = next(row for row in result.rows if row.product_code == "COFFEE")
    assert coffee.residual == Decimal("-8")
    assert coffee.consumption == Decimal("150")


def test_shortage_money_negatives_only() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="s1",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-10"), "SUGAR": Decimal("5")},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p1", sales={"COFFEE": Decimal("100"), "SUGAR": Decimal("100")}))

    result = AggregateSettlementClusters(events, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s1"}),
        prefs=_prefs(prices={"COFFEE": Decimal("2"), "SUGAR": Decimal("1")}),
    )

    by_code = {row.product_code: row for row in result.rows}
    assert by_code["COFFEE"].shortage_money == Decimal("20")
    assert by_code["SUGAR"].shortage_money == Decimal("0")
    assert result.shortage_money_total == Decimal("20")


def test_loss_pct_undefined_when_zero_consumption() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="s1",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-1")},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p1", sales={}))

    result = AggregateSettlementClusters(events, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s1"}),
        prefs=_prefs(prices={"COFFEE": Decimal("1")}),
    )

    coffee = next(row for row in result.rows if row.product_code == "COFFEE")
    assert coffee.consumption == Decimal("0")
    assert coffee.loss_pct is None
    assert coffee.loss_pct_points is None


def test_loss_pct_points_are_integer_percent() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="s1",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-145317")},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p1", sales={"COFFEE": Decimal("100000")}))

    result = AggregateSettlementClusters(events, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s1"}),
        prefs=_prefs(prices={"COFFEE": Decimal("1")}),
    )

    coffee = next(row for row in result.rows if row.product_code == "COFFEE")
    assert coffee.loss_pct == Decimal("1.45317")
    assert coffee.loss_pct_points == 145


def test_format_analysis_rubles_rounds_half_up() -> None:
    assert format_analysis_rubles(Decimal("18838.89000")) == 18839
    assert format_analysis_rubles(Decimal("27909.000")) == 27909
    assert format_analysis_rubles(Decimal("10.5")) == 11
    assert format_analysis_rubles(Decimal("10.4")) == 10


class _NameCatalog:
    def try_resolve_by_code(self, product_code: str) -> object | None:
        if product_code == "COFFEE":
            return type("Spec", (), {"name": "Кофе зерно"})()
        return None

    def resolve_by_code(self, product_code: str) -> object:
        spec = self.try_resolve_by_code(product_code)
        if spec is None:
            raise ValueError(product_code)
        return spec


def test_aggregate_row_uses_catalog_product_name() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="s1",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-1"), "SUGAR": Decimal("-1")},
        ),
        expected_version=0,
    )
    snapshots.save(
        _snapshot("p1", sales={"COFFEE": Decimal("10"), "SUGAR": Decimal("10")}),
    )

    result = AggregateSettlementClusters(events, snapshots, catalog=_NameCatalog()).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s1"}),
        prefs=_prefs(prices={"COFFEE": Decimal("1"), "SUGAR": Decimal("1")}),
    )

    by_code = {row.product_code: row for row in result.rows}
    assert by_code["COFFEE"].product_name == "Кофе зерно"
    assert by_code["SUGAR"].product_name == "SUGAR"


def test_excess_uses_full_residual_when_zero_consumption() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="s1",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-10")},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p1", sales={}))

    result = AggregateSettlementClusters(events, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s1"}),
        prefs=_prefs(prices={"COFFEE": Decimal("1")}, n=Decimal("2")),
    )

    coffee = next(row for row in result.rows if row.product_code == "COFFEE")
    assert coffee.excess_qty == Decimal("10")


def test_excess_over_allowance() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="s1",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-1067")},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p1", sales={"COFFEE": Decimal("56411")}))
    prefs = _prefs(prices={"COFFEE": Decimal("1")}, n=Decimal("2"))

    within = AggregateSettlementClusters(events, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s1"}),
        prefs=prefs,
    )
    coffee_within = next(row for row in within.rows if row.product_code == "COFFEE")
    assert coffee_within.excess_qty == Decimal("0")

    events_over = InMemoryTechnicianSettlementEventStore()
    events_over.append(
        _completed(
            session_id="s2",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-2000")},
        ),
        expected_version=0,
    )
    over = AggregateSettlementClusters(events_over, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s2"}),
        prefs=prefs,
    )
    coffee_over = next(row for row in over.rows if row.product_code == "COFFEE")
    allowed = Decimal("2") / Decimal("100") * Decimal("56411")
    assert coffee_over.excess_qty == Decimal("2000") - allowed


def test_recoverable_vs_loss_subtotals() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="s1",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={"COFFEE": Decimal("-10"), "SUGAR": Decimal("-4")},
        ),
        expected_version=0,
    )
    snapshots.save(_snapshot("p1", sales={"COFFEE": Decimal("100"), "SUGAR": Decimal("100")}))

    result = AggregateSettlementClusters(events, snapshots).execute(
        technician_id=_TECH,
        session_ids=frozenset({"s1"}),
        prefs=_prefs(
            prices={"COFFEE": Decimal("2"), "SUGAR": Decimal("1")},
            recoverable=frozenset({"COFFEE"}),
        ),
    )

    by_code = {row.product_code: row for row in result.rows}
    assert by_code["COFFEE"].recoverable is True
    assert by_code["SUGAR"].recoverable is False
    assert result.recoverable_shortage_money == Decimal("20")
    assert result.loss_shortage_money == Decimal("4")
    assert result.recoverable_excess_money == by_code["COFFEE"].excess_money
    assert result.loss_excess_money == by_code["SUGAR"].excess_money


def test_aggregate_unknown_session_fails_closed() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    snapshots = InMemoryPeriodReconciliationRepository()
    events.append(
        _completed(
            session_id="known",
            mode="inventory_delta",
            period_ids=("p1",),
            residual={},
        ),
        expected_version=0,
    )

    with pytest.raises(UnknownAnalysisSession) as exc_info:
        AggregateSettlementClusters(events, snapshots).execute(
            technician_id=_TECH,
            session_ids=frozenset({"known", "ghost"}),
            prefs=_prefs(),
        )
    assert exc_info.value.session_id == "ghost"
