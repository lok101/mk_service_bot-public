from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.application.machine_pnl import PeriodPnl, PnlWarning
from src.application.machine_pnl.models import FULL_SLICE_KEY, make_pnl_id
from src.application.machine_pnl.opex_breakdown import OPEX_BREAKDOWN_KEYS, empty_opex_breakdown
from src.domain.ids import MachineId


def test_period_pnl_holds_full_shape_with_zero_residual_opex() -> None:
    pnl = PeriodPnl(
        pnl_id=make_pnl_id("a:b"),
        period_id="a:b",
        slice_key=FULL_SLICE_KEY,
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        closed_at=datetime(2026, 1, 10, tzinfo=UTC),
        revenue=Decimal("100.00"),
        cogs_expected=Decimal("40.00"),
        cogs_actual=Decimal("42.00"),
        allocated_shortage=Decimal("0.00"),
        allocated_surplus=Decimal("0.00"),
        opex=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        net_before_residual=Decimal("58.00"),
        net_after_shortage=Decimal("58.00"),
        warnings=(PnlWarning(code="null_price", message="null_price_count=1"),),
    )
    assert pnl.allocated_shortage == Decimal("0.00")
    assert pnl.opex == Decimal("0.00")
    assert pnl.opex_breakdown == empty_opex_breakdown()
    assert pnl.warnings[0].code == "null_price"


def test_period_pnl_has_no_unallocated_residual_field() -> None:
    pnl = PeriodPnl(
        pnl_id=make_pnl_id("p1"),
        period_id="p1",
        slice_key=FULL_SLICE_KEY,
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        revenue=Decimal("100.00"),
        cogs_expected=Decimal("10.00"),
        cogs_actual=Decimal("12.00"),
        allocated_shortage=Decimal("0.00"),
        allocated_surplus=Decimal("0.00"),
        opex=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        net_before_residual=Decimal("88.00"),
        net_after_shortage=Decimal("88.00"),
        warnings=(),
    )
    assert not hasattr(pnl, "unallocated_residual_by_sku")
    assert dict(pnl.opex_breakdown)["route_fuel"] == Decimal("0.00")


def test_period_pnl_accepts_null_tax_in_breakdown() -> None:
    base = dict(empty_opex_breakdown())
    base["tax"] = None
    breakdown = tuple((k, base[k]) for k in OPEX_BREAKDOWN_KEYS)
    pnl = PeriodPnl(
        pnl_id=make_pnl_id("p-1"),
        period_id="p-1",
        slice_key=FULL_SLICE_KEY,
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
        closed_at=datetime(2026, 1, 10, tzinfo=UTC),
        revenue=Decimal("100.00"),
        cogs_expected=Decimal("0.00"),
        cogs_actual=Decimal("0.00"),
        allocated_shortage=Decimal("0.00"),
        allocated_surplus=Decimal("0.00"),
        opex=Decimal("10.00"),
        opex_breakdown=breakdown,
        net_before_residual=Decimal("90.00"),
        net_after_shortage=Decimal("90.00"),
        warnings=(),
    )
    assert dict(pnl.opex_breakdown)["tax"] is None


def test_period_pnl_optional_location_and_technician_default_none() -> None:
    pnl = PeriodPnl(
        pnl_id=make_pnl_id("p1"),
        period_id="p1",
        slice_key=FULL_SLICE_KEY,
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        revenue=Decimal("0.00"),
        cogs_expected=Decimal("0.00"),
        cogs_actual=Decimal("0.00"),
        allocated_shortage=Decimal("0.00"),
        allocated_surplus=Decimal("0.00"),
        opex=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        net_before_residual=Decimal("0.00"),
        net_after_shortage=Decimal("0.00"),
        warnings=(),
    )
    assert pnl.location_id is None
    assert pnl.technician_id is None


def test_period_pnl_accepts_location_and_technician() -> None:
    pnl = PeriodPnl(
        pnl_id=make_pnl_id("p1"),
        period_id="p1",
        slice_key=FULL_SLICE_KEY,
        machine_id=MachineId("101"),
        opened_at=datetime(2026, 5, 1, tzinfo=UTC),
        closed_at=datetime(2026, 5, 10, tzinfo=UTC),
        revenue=Decimal("0.00"),
        cogs_expected=Decimal("0.00"),
        cogs_actual=Decimal("0.00"),
        allocated_shortage=Decimal("0.00"),
        allocated_surplus=Decimal("0.00"),
        opex=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        net_before_residual=Decimal("0.00"),
        net_after_shortage=Decimal("0.00"),
        warnings=(),
        location_id="loc-a",
        technician_id="tech-1",
    )
    assert pnl.location_id == "loc-a"
    assert pnl.technician_id == "tech-1"
