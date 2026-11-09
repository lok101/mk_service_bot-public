from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.application.machine_pnl.opex_params import (
    FixtureMachineOpExRow,
    FixtureOpExParamsCatalog,
    FixtureRateRow,
)
from src.domain.ids import MachineId

_MID = MachineId("101")


def test_opex_params_dated_resolve_as_of() -> None:
    catalog = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=_MID,
                valid_from=date(2026, 1, 1),
                rent_monthly=Decimal("100"),
                rent_percent=None,
                duty_mode="patent",
                patent_monthly=Decimal("50"),
                tax_percent=None,
                acquiring_percent=Decimal("1"),
                acquiring_fee_per_sale=Decimal("0.5"),
                terminal_monthly=None,
            ),
            FixtureMachineOpExRow(
                machine_id=_MID,
                valid_from=date(2026, 6, 1),
                rent_monthly=Decimal("200"),
                rent_percent=None,
                duty_mode="patent",
                patent_monthly=Decimal("50"),
                tax_percent=None,
                acquiring_percent=Decimal("1"),
                acquiring_fee_per_sale=Decimal("0.5"),
                terminal_monthly=None,
            ),
        ),
        labor_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("40")),),
        terminal_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("310")),),
    )
    early = catalog.resolve(_MID, as_of=date(2026, 3, 1))
    late = catalog.resolve(_MID, as_of=date(2026, 7, 1))
    assert early.rent_monthly == Decimal("100")
    assert late.rent_monthly == Decimal("200")
    assert early.terminal_monthly == Decimal("310")  # global fallback


def test_opex_params_labor_uses_global_only() -> None:
    catalog = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=_MID,
                valid_from=date(2026, 1, 1),
                rent_monthly=Decimal("100"),
                rent_percent=None,
                duty_mode="patent",
                patent_monthly=Decimal("50"),
                tax_percent=None,
                acquiring_percent=Decimal("1"),
                acquiring_fee_per_sale=Decimal("0.5"),
                terminal_monthly=None,
            ),
        ),
        labor_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("40")),),
        terminal_global_rows=(),
    )
    resolved = catalog.resolve(_MID, as_of=date(2026, 3, 1))
    assert resolved.labor_rate == Decimal("40")
    assert resolved.missing_labor_rate is False


def test_opex_params_missing_rent_monthly_sets_incomplete() -> None:
    catalog = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=_MID,
                valid_from=date(2026, 1, 1),
                rent_monthly=None,
                rent_percent=Decimal("10"),
                duty_mode="patent",
                patent_monthly=Decimal("50"),
                tax_percent=None,
                acquiring_percent=Decimal("1"),
                acquiring_fee_per_sale=Decimal("0.5"),
                terminal_monthly=None,
            ),
        ),
        labor_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("40")),),
        terminal_global_rows=(),
    )
    resolved = catalog.resolve(_MID, as_of=date(2026, 3, 1))
    assert resolved.params_incomplete is True
    assert resolved.rent_monthly is None


def test_opex_params_missing_machine_no_incomplete_flag() -> None:
    catalog = FixtureOpExParamsCatalog(
        machine_rows=(),
        labor_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("40")),),
        terminal_global_rows=(),
    )
    resolved = catalog.resolve(_MID, as_of=date(2026, 3, 1))
    assert resolved.params_incomplete is False
    assert resolved.labor_rate == Decimal("40")
    assert resolved.missing_labor_rate is False
