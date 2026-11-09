from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.global_opex_sheet import GlobalOpExSheetRow
from src.application.machine_pnl.opex_params import (
    EffectiveOpExParams,
    FixtureOpExParamsCatalog,
)
from src.domain.ids import MachineId


def _latest_global(
    rows: tuple[GlobalOpExSheetRow, ...],
    *,
    as_of: date,
) -> GlobalOpExSheetRow | None:
    eligible = [row for row in rows if row.valid_from <= as_of]
    if not eligible:
        return None
    return max(eligible, key=lambda row: row.valid_from)


@beartype
@dataclass(frozen=True, slots=True)
class ComposedOpExParamsCatalog:
    """Sheets global SCD rates + machine fixture rows (OpExParamsPort)."""

    machine: FixtureOpExParamsCatalog
    global_rows: tuple[GlobalOpExSheetRow, ...]

    @beartype
    def resolve(self, machine_id: MachineId, *, as_of: date) -> EffectiveOpExParams:
        base = self.machine.resolve(machine_id, as_of=as_of)
        global_row = _latest_global(self.global_rows, as_of=as_of)
        if global_row is None:
            return base

        labor_rate: Decimal | None = global_row.labor_rate_global
        missing_labor_rate = labor_rate is None

        return EffectiveOpExParams(
            rent_monthly=base.rent_monthly,
            rent_percent=base.rent_percent,
            duty_mode=base.duty_mode,
            patent_monthly=base.patent_monthly,
            tax_percent=base.tax_percent,
            acquiring_percent=global_row.acquiring_percent,
            acquiring_fee_per_sale=global_row.acquiring_fee_per_sale,
            terminal_monthly=global_row.terminal_monthly,
            labor_rate=labor_rate,
            params_incomplete=base.params_incomplete,
            missing_labor_rate=missing_labor_rate,
        )
