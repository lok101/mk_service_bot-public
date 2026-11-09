from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from src.application.machine_pnl.composed_opex_params import ComposedOpExParamsCatalog
from src.application.machine_pnl.global_opex_sheet import GlobalOpExSheetRow
from src.application.machine_pnl.opex import compute_opex
from src.application.machine_pnl.opex_params import (
    FixtureMachineOpExRow,
    FixtureOpExParamsCatalog,
)
from src.domain.ids import MachineId

_ZERO = Decimal("0.00")


def test_composed_opex_params_uses_global_sheet_rates() -> None:
    # happy: SCD global; acquiring/terminal/labor с global; duty с machine fixture
    machine = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=MachineId("101"),
                valid_from=date(2026, 1, 1),
                rent_monthly=None,
                rent_percent=None,
                duty_mode="patent",
                patent_monthly=Decimal("100"),
                tax_percent=None,
                acquiring_percent=Decimal("99"),  # ignored when global present
                acquiring_fee_per_sale=Decimal("99"),
                terminal_monthly=None,
            ),
        ),
    )
    global_rows = (
        GlobalOpExSheetRow(
            valid_from=date(2026, 1, 1),
            labor_rate_global=Decimal("50"),
            acquiring_percent=Decimal("2.5"),
            acquiring_fee_per_sale=Decimal("0.2"),
            terminal_monthly=Decimal("900"),
        ),
        GlobalOpExSheetRow(
            valid_from=date(2026, 6, 1),
            labor_rate_global=Decimal("60"),
            acquiring_percent=Decimal("3"),
            acquiring_fee_per_sale=Decimal("0.3"),
            terminal_monthly=Decimal("1000"),
        ),
    )
    catalog = ComposedOpExParamsCatalog(machine=machine, global_rows=global_rows)
    params = catalog.resolve(MachineId("101"), as_of=date(2026, 7, 1))
    assert params.labor_rate == Decimal("60")
    assert params.missing_labor_rate is False
    assert params.acquiring_percent == Decimal("3")
    assert params.acquiring_fee_per_sale == Decimal("0.3")
    assert params.terminal_monthly == Decimal("1000")
    assert params.duty_mode == "patent"
    assert params.patent_monthly == Decimal("100")


def test_composed_opex_params_no_global_row_missing_labor() -> None:
    # edge
    catalog = ComposedOpExParamsCatalog(
        machine=FixtureOpExParamsCatalog.default(),
        global_rows=(),
    )
    params = catalog.resolve(MachineId("101"), as_of=date(2026, 7, 1))
    assert params.params_incomplete is False
    assert params.missing_labor_rate is True
    assert params.labor_rate is None


def test_composed_opex_params_terminal_from_global_ignores_machine() -> None:
    # edge: machine.terminal_monthly задан, но SoT — global sheet
    machine = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=MachineId("101"),
                valid_from=date(2026, 1, 1),
                rent_monthly=Decimal("1"),
                rent_percent=None,
                duty_mode="patent",
                patent_monthly=Decimal("100"),
                tax_percent=None,
                acquiring_percent=None,
                acquiring_fee_per_sale=None,
                terminal_monthly=Decimal("999"),  # must be ignored when global present
            ),
        ),
    )
    global_rows = (
        GlobalOpExSheetRow(
            valid_from=date(2026, 1, 1),
            labor_rate_global=Decimal("50"),
            acquiring_percent=Decimal("2.5"),
            acquiring_fee_per_sale=Decimal("0.2"),
            terminal_monthly=Decimal("1000"),
        ),
    )
    params = ComposedOpExParamsCatalog(machine=machine, global_rows=global_rows).resolve(
        MachineId("101"), as_of=date(2026, 7, 1)
    )
    assert params.terminal_monthly == Decimal("1000")


def test_composed_empty_machine_global_sheet_no_incomplete_warning() -> None:
    catalog = ComposedOpExParamsCatalog(
        machine=FixtureOpExParamsCatalog.default(),
        global_rows=(
            GlobalOpExSheetRow(
                valid_from=date(2026, 1, 1),
                labor_rate_global=Decimal("50"),
                acquiring_percent=Decimal("2"),
                acquiring_fee_per_sale=Decimal("1.50"),
                terminal_monthly=Decimal("310"),
            ),
        ),
    )
    params = catalog.resolve(MachineId("vm-any"), as_of=date(2026, 5, 10))
    assert params.params_incomplete is False
    assert params.acquiring_percent == Decimal("2")
    assert params.terminal_monthly == Decimal("310")

    opened = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    closed = datetime(2026, 5, 11, 12, 0, tzinfo=UTC)
    result = compute_opex(
        params=params,
        revenue=Decimal("1000"),
        sale_count=4,
        maintenance_count=1,
        opened_at=opened,
        closed_at=closed,
        rent_fixed=_ZERO,
        rent_percent=_ZERO,
    )
    by_key = dict(result.breakdown)
    assert by_key["acquiring_percent"] == Decimal("20.00")
    assert by_key["acquiring_per_sale"] == Decimal("6.00")
    assert by_key["terminal"] == Decimal("100.00")
    assert by_key["labor"] == Decimal("50.00")
    assert not any(w.code == "opex_params_incomplete" for w in result.warnings)
