from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.machine_pnl.fakes import (
    InMemoryPeriodSnapshotReader,
    InMemoryUnitCostCatalog,
)

from src.application.machine_pnl.allocate_residual import allocate_residual_for_period
from src.application.machine_pnl.errors import (
    AmbiguousResidualSessionError,
    IncompleteSnapshotError,
    MachinePnlError,
    MissingUnitCostError,
    SnapshotNotFoundError,
)
from src.application.machine_pnl.residual_ports import ResidualSessionView
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation

_SKU = "coffee-beans"
_SKU_B = "cups"
_TECH = TechnicianId("tech-1")
_ANCHOR = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


def _line(sales_total: Decimal, *, product_code: str = _SKU) -> ReconciliationLine:
    return ReconciliationLine(
        product_code=product_code,
        actual_prev=Decimal("10"),
        actual=Decimal("7"),
        calculated=Decimal("5"),
        delta=Decimal("2"),
        loads_total=Decimal("0"),
        sales_total=sales_total,
    )


def _snap(
    period_id: str,
    *,
    sales_total: Decimal = Decimal("1"),
    machine_id: str = "101",
    status: str = "complete",
    reconciled: bool = True,
    lines: tuple[ReconciliationLine, ...] | None = None,
) -> ResponsibilityPeriodReconciliation:
    if lines is None:
        lines = (_line(sales_total),)
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=MachineId(machine_id),
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("rev-o"),
        closing_revision_id=RevisionId("rev-c"),
        opened_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
        lines=lines,
        sales_lines=(),
        load_count=0,
        status=status,  # type: ignore[arg-type]
        reconciled=reconciled,
    )


def _session(
    *,
    period_ids: tuple[str, ...] = ("p1", "p2"),
    residual_by_sku: dict[str, Decimal] | None = None,
) -> ResidualSessionView:
    if residual_by_sku is None:
        residual_by_sku = {_SKU: Decimal("-10")}
    return ResidualSessionView(
        session_id="sess-1",
        technician_id=_TECH.value,
        anchor_at=_ANCHOR,
        period_ids=period_ids,
        residual_by_sku=residual_by_sku,
    )


def test_allocate_residual_two_coffee_periods_proportional() -> None:
    # residual qty -10 (shortage); cost 2.00 → money_total=20
    # weights: p1 sales=3, p2 sales=1 → W=4; share_p1 = 20 * 3/4 = 15
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p1", sales_total=Decimal("3")))
    snapshots.save(_snap("p2", sales_total=Decimal("1")))
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("2.00"))
    session = _session(residual_by_sku={_SKU: Decimal("-10")})

    result = allocate_residual_for_period(
        period_id="p1",
        session=session,
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    assert result.allocated_shortage == Decimal("15.00")
    assert result.allocated_surplus == Decimal("0.00")
    assert result.warnings == ()


def test_allocate_residual_w_zero_warning_empty_unallocated() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p1", sales_total=Decimal("0")))
    snapshots.save(_snap("p2", sales_total=Decimal("0")))
    catalog = InMemoryUnitCostCatalog()
    residual_qty = Decimal("-4")
    session = _session(residual_by_sku={_SKU: residual_qty})

    result = allocate_residual_for_period(
        period_id="p1",
        session=session,
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    assert result.allocated_shortage == Decimal("0.00")
    assert result.allocated_surplus == Decimal("0.00")
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.code == "unallocatable_residual"
    assert warning.sku == _SKU
    assert _SKU in warning.message
    assert str(residual_qty) in warning.message
    assert not hasattr(result, "unallocated_residual_by_sku")


def test_allocate_residual_shortage_and_surplus_signs() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    lines = (
        _line(Decimal("2"), product_code=_SKU),
        _line(Decimal("2"), product_code=_SKU_B),
    )
    snapshots.save(_snap("p1", lines=lines))
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("3.00"))
    catalog.set(_SKU_B, as_of=_ANCHOR.date(), cost=Decimal("4.00"))
    session = _session(
        period_ids=("p1",),
        residual_by_sku={_SKU: Decimal("-2"), _SKU_B: Decimal("1")},
    )

    result = allocate_residual_for_period(
        period_id="p1",
        session=session,
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    # shortage: abs(-2)*3 = 6; surplus: 1*4 = 4
    assert result.allocated_shortage == Decimal("6.00")
    assert result.allocated_surplus == Decimal("4.00")


def test_allocate_residual_zero_residual_qty_skipped() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    catalog = InMemoryUnitCostCatalog()

    empty = allocate_residual_for_period(
        period_id="p1",
        session=_session(period_ids=("p1",), residual_by_sku={}),
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )
    zeroed = allocate_residual_for_period(
        period_id="p1",
        session=_session(period_ids=("p1",), residual_by_sku={_SKU: Decimal("0")}),
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    assert empty.allocated_shortage == Decimal("0.00")
    assert empty.allocated_surplus == Decimal("0.00")
    assert empty.warnings == ()
    assert zeroed.allocated_shortage == Decimal("0.00")
    assert zeroed.allocated_surplus == Decimal("0.00")
    assert zeroed.warnings == ()


def test_allocate_residual_negative_sales_total_weight_zero() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p-a", sales_total=Decimal("-5")))
    snapshots.save(_snap("p-b", sales_total=Decimal("2")))
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("2.50"))
    session = _session(
        period_ids=("p-a", "p-b"),
        residual_by_sku={_SKU: Decimal("-4")},
    )

    result = allocate_residual_for_period(
        period_id="p-b",
        session=session,
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    # W only from p-b (=2); money_total = 4 * 2.50 = 10; full share to p-b
    assert result.allocated_shortage == Decimal("10.00")
    assert result.allocated_surplus == Decimal("0.00")
    assert result.warnings == ()


def test_allocate_residual_snack_sibling_excluded_from_weights() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("coffee-p", sales_total=Decimal("2"), machine_id="101"))
    snapshots.save(_snap("snack-p", sales_total=Decimal("100"), machine_id="501"))
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("5.00"))
    session = _session(
        period_ids=("coffee-p", "snack-p"),
        residual_by_sku={_SKU: Decimal("-3")},
    )

    result = allocate_residual_for_period(
        period_id="coffee-p",
        session=session,
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    # W only coffee (=2); money_total = 3 * 5 = 15; 100% to coffee-p
    assert result.allocated_shortage == Decimal("15.00")
    assert result.allocated_surplus == Decimal("0.00")
    assert result.warnings == ()


def test_allocate_residual_round_half_up_on_aggregates() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p1", sales_total=Decimal("1")))
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("1.005"))
    session = _session(period_ids=("p1",), residual_by_sku={_SKU: Decimal("-1")})

    result = allocate_residual_for_period(
        period_id="p1",
        session=session,
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    # money_total/share = 1.005 → ROUND_HALF_UP → 1.01
    assert result.allocated_shortage == Decimal("1.01")
    assert result.allocated_surplus == Decimal("0.00")


def test_allocate_residual_sibling_missing_fails() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p1", sales_total=Decimal("1")))
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("1.00"))
    session = _session(period_ids=("p1", "missing-p"), residual_by_sku={_SKU: Decimal("-1")})

    with pytest.raises(SnapshotNotFoundError) as exc_info:
        allocate_residual_for_period(
            period_id="p1",
            session=session,
            snapshots=snapshots,
            unit_cost_catalog=catalog,
        )

    assert exc_info.value.period_id == "missing-p"


@pytest.mark.parametrize(
    ("status", "reconciled", "expected_status"),
    [
        ("pending_sales", True, "pending_sales"),
        ("complete", False, "unreconciled"),
    ],
)
def test_allocate_residual_sibling_incomplete_or_unreconciled_fails(
    status: str,
    reconciled: bool,
    expected_status: str,
) -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p1", sales_total=Decimal("1")))
    snapshots.save(_snap("p2", sales_total=Decimal("1"), status=status, reconciled=reconciled))
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("1.00"))
    session = _session(period_ids=("p1", "p2"), residual_by_sku={_SKU: Decimal("-1")})

    with pytest.raises(IncompleteSnapshotError) as exc_info:
        allocate_residual_for_period(
            period_id="p1",
            session=session,
            snapshots=snapshots,
            unit_cost_catalog=catalog,
        )

    assert exc_info.value.period_id == "p2"
    assert exc_info.value.status == expected_status


def test_allocate_residual_missing_unit_cost_fails() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p1", sales_total=Decimal("1")))
    catalog = InMemoryUnitCostCatalog()
    session = _session(period_ids=("p1",), residual_by_sku={_SKU: Decimal("-1")})

    with pytest.raises(MissingUnitCostError) as exc_info:
        allocate_residual_for_period(
            period_id="p1",
            session=session,
            snapshots=snapshots,
            unit_cost_catalog=catalog,
        )

    assert exc_info.value.product_code == _SKU
    assert exc_info.value.as_of == _ANCHOR.date().isoformat()
    assert exc_info.value.period_id == "p1"


def test_allocate_residual_uses_anchor_at_date_for_unit_cost() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p1", sales_total=Decimal("1")))
    catalog = InMemoryUnitCostCatalog()
    closed_at_date = datetime(2026, 5, 10, 12, 0, tzinfo=UTC).date()
    catalog.set(_SKU, as_of=closed_at_date, cost=None)
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("7.00"))
    session = _session(period_ids=("p1",), residual_by_sku={_SKU: Decimal("-2")})

    result = allocate_residual_for_period(
        period_id="p1",
        session=session,
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    assert result.allocated_shortage == Decimal("14.00")


def test_allocate_residual_sorted_sku_warning_order() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snap("p1", sales_total=Decimal("0")))
    catalog = InMemoryUnitCostCatalog()
    residual = {"z-sku": Decimal("-1"), "a-sku": Decimal("-2")}
    session = _session(period_ids=("p1",), residual_by_sku=residual)

    result = allocate_residual_for_period(
        period_id="p1",
        session=session,
        snapshots=snapshots,
        unit_cost_catalog=catalog,
    )

    assert [w.sku for w in result.warnings] == ["a-sku", "z-sku"]
    assert all(w.code == "unallocatable_residual" for w in result.warnings)


def test_ambiguous_residual_session_error_is_machine_pnl_error() -> None:
    err = AmbiguousResidualSessionError(period_id="p1", technician_id="tech-1", count=2)
    assert isinstance(err, MachinePnlError)
    assert err.period_id == "p1"
    assert err.count == 2
