from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.technician_settlement.settlement_analysis import (
    BuildPeriodAnalysisView,
    BuildSessionAnalysisView,
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
_OTHER = TechnicianId("20020")


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


def test_session_view_reads_committed_event() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    events.append(
        _committed(
            session_id="sess-committed",
            mode="inventory_delta",
            period_ids=("p-a", "p-b"),
            residual={"COFFEE": Decimal("-5")},
            warehouse_delta={"COFFEE": Decimal("12")},
        ),
        expected_version=0,
    )

    view = BuildSessionAnalysisView(events).execute(
        technician_id=_TECH,
        session_id="sess-committed",
    )

    assert view is not None
    assert view.session_id == "sess-committed"
    assert view.warehouse_delta_by_sku == {"COFFEE": Decimal("12")}
    assert view.residual_by_sku == {"COFFEE": Decimal("-5")}
    assert view.period_ids == ("p-a", "p-b")
    assert view.mode == "inventory_delta"


def test_session_view_exposes_warehouse_and_residual() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    events.append(
        _completed(
            session_id="sess-1",
            mode="inventory_delta",
            period_ids=("p-a", "p-b"),
            residual={"COFFEE": Decimal("-3")},
            warehouse_delta={"COFFEE": Decimal("10")},
        ),
        expected_version=0,
    )

    view = BuildSessionAnalysisView(events).execute(
        technician_id=_TECH,
        session_id="sess-1",
    )

    assert view is not None
    assert view.session_id == "sess-1"
    assert view.warehouse_delta_by_sku == {"COFFEE": Decimal("10")}
    assert view.residual_by_sku == {"COFFEE": Decimal("-3")}
    assert view.period_ids == ("p-a", "p-b")
    assert view.mode == "inventory_delta"


def test_session_view_wrong_tech_or_missing() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    events.append(
        _completed(
            session_id="sess-1",
            mode="inventory_delta",
            period_ids=("p-a",),
            residual={},
        ),
        expected_version=0,
    )

    assert (
        BuildSessionAnalysisView(events).execute(
            technician_id=_OTHER,
            session_id="sess-1",
        )
        is None
    )
    assert (
        BuildSessionAnalysisView(events).execute(
            technician_id=_TECH,
            session_id="missing",
        )
        is None
    )


def test_period_view_lines() -> None:
    snapshots = InMemoryPeriodReconciliationRepository()
    opened = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    closed = datetime(2026, 6, 8, 17, 0, tzinfo=UTC)
    snapshots.save(
        ResponsibilityPeriodReconciliation(
            period_id="p-1",
            machine_id=MachineId("vm-01"),
            responsible_technician_id=_TECH,
            opening_revision_id=RevisionId("open-p-1"),
            closing_revision_id=RevisionId("close-p-1"),
            opened_at=opened,
            closed_at=closed,
            lines=(
                ReconciliationLine(
                    product_code="COFFEE",
                    actual_prev=Decimal("0"),
                    actual=Decimal("0"),
                    calculated=Decimal("0"),
                    delta=Decimal("-5"),
                    loads_total=Decimal("20"),
                    sales_total=Decimal("100"),
                ),
                ReconciliationLine(
                    product_code="SUGAR",
                    actual_prev=Decimal("0"),
                    actual=Decimal("0"),
                    calculated=Decimal("0"),
                    delta=Decimal("1"),
                    loads_total=Decimal("0"),
                    sales_total=Decimal("50"),
                ),
            ),
            sales_lines=(),
            load_count=0,
            status="complete",
            ledger_posted=True,
            location_name="Market",
        )
    )

    view = BuildPeriodAnalysisView(snapshots).execute("p-1")

    assert view is not None
    assert view.period_id == "p-1"
    assert view.location_name == "Market"
    assert view.opened_at == opened
    assert view.closed_at == closed
    assert len(view.lines) == 2
    coffee = next(line for line in view.lines if line.product_code == "COFFEE")
    assert coffee.sales_total == Decimal("100")
    assert coffee.delta == Decimal("-5")
    assert coffee.loads_total == Decimal("20")
    assert coffee.product_name == "COFFEE"


class _PeriodNames:
    def location_name(self, machine_id: MachineId) -> str | None:
        return "Школа №1"

    def technician_name(self, technician_id: TechnicianId) -> str | None:
        return None


class _PeriodCatalog:
    def try_resolve_by_code(self, product_code: str) -> object | None:
        if product_code == "COFFEE":
            return type("Spec", (), {"name": "Кофе зерно"})()
        return None

    def resolve_by_code(self, product_code: str) -> object:
        spec = self.try_resolve_by_code(product_code)
        if spec is None:
            raise ValueError(product_code)
        return spec


def test_period_view_resolves_blank_location_and_product_name() -> None:
    snapshots = InMemoryPeriodReconciliationRepository()
    snapshots.save(
        ResponsibilityPeriodReconciliation(
            period_id="p-blank",
            machine_id=MachineId("vm-01"),
            responsible_technician_id=_TECH,
            opening_revision_id=RevisionId("open-p-blank"),
            closing_revision_id=RevisionId("close-p-blank"),
            opened_at=datetime(2026, 6, 1, 9, 0, tzinfo=UTC),
            closed_at=datetime(2026, 6, 8, 17, 0, tzinfo=UTC),
            lines=(
                ReconciliationLine(
                    product_code="COFFEE",
                    actual_prev=Decimal("0"),
                    actual=Decimal("0"),
                    calculated=Decimal("0"),
                    delta=Decimal("-5"),
                    sales_total=Decimal("100"),
                ),
            ),
            sales_lines=(),
            load_count=0,
            status="complete",
            ledger_posted=True,
            location_name="",
        )
    )

    view = BuildPeriodAnalysisView(
        snapshots,
        party_names_lookup=_PeriodNames(),
        catalog=_PeriodCatalog(),
    ).execute("p-blank")

    assert view is not None
    assert view.location_name == "Школа №1"
    assert view.lines[0].product_name == "Кофе зерно"


def test_session_view_uses_product_names() -> None:
    events = InMemoryTechnicianSettlementEventStore()
    events.append(
        _completed(
            session_id="sess-1",
            mode="inventory_delta",
            period_ids=("p-a",),
            residual={"COFFEE": Decimal("-3")},
            warehouse_delta={"COFFEE": Decimal("10")},
        ),
        expected_version=0,
    )

    view = BuildSessionAnalysisView(events, catalog=_PeriodCatalog()).execute(
        technician_id=_TECH,
        session_id="sess-1",
    )

    assert view is not None
    assert view.warehouse_delta_rows[0].product_name == "Кофе зерно"
    assert view.residual_rows[0].product_name == "Кофе зерно"
