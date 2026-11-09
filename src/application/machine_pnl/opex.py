from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.models import PnlWarning
from src.application.machine_pnl.money import round_money
from src.application.machine_pnl.opex_breakdown import OPEX_BREAKDOWN_KEYS
from src.application.machine_pnl.opex_params import EffectiveOpExParams

_ZERO = Decimal("0.00")


@beartype
@dataclass(frozen=True, slots=True)
class OpExComputation:
    breakdown: tuple[tuple[str, Decimal | None], ...]
    opex: Decimal
    warnings: tuple[PnlWarning, ...]


@beartype
def period_days(*, opened_at: datetime, closed_at: datetime) -> int:
    return max(1, (closed_at.date() - opened_at.date()).days)


def _days_in_calendar_month(d: datetime) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _monthly_prorata(monthly: Decimal, *, days: int, closed_at: datetime) -> Decimal:
    month_days = _days_in_calendar_month(closed_at)
    return round_money(monthly * Decimal(days) / Decimal(month_days))


def _percent_of_revenue(percent: Decimal, revenue: Decimal) -> Decimal:
    return round_money((percent / Decimal("100")) * revenue)


@beartype
def compute_opex(
    *,
    params: EffectiveOpExParams,
    revenue: Decimal,
    sale_count: int,
    maintenance_count: int,
    opened_at: datetime,
    closed_at: datetime,
    rent_fixed: Decimal,
    rent_percent: Decimal,
    tax_enabled: bool = False,
) -> OpExComputation:
    days = period_days(opened_at=opened_at, closed_at=closed_at)
    warnings: list[PnlWarning] = []

    if params.params_incomplete:
        warnings.append(
            PnlWarning(code="opex_params_incomplete", message="OpEx params incomplete for machine")
        )
    if params.missing_labor_rate:
        warnings.append(
            PnlWarning(code="missing_labor_rate", message="Labor rate missing for machine")
        )

    # rent SoT = location occupancy slices (kwargs); params.rent_* ignored for gate/Σ
    rent_fixed_money = round_money(rent_fixed)
    rent_percent_money = round_money(rent_percent)

    patent = _ZERO
    if params.duty_mode == "patent":
        if params.patent_monthly is not None:
            patent = _monthly_prorata(params.patent_monthly, days=days, closed_at=closed_at)
        else:
            warnings.append(
                PnlWarning(
                    code="patent_pending_manual",
                    message="Patent amount missing; pending manual attachment",
                )
            )

    tax: Decimal | None
    if not tax_enabled:
        # Outside domain: snapshot marks tax undefined; no sheet ingest / no % from params.
        tax = None
        warnings.append(
            PnlWarning(
                code="tax_pending_manual",
                message="Tax ingest disabled; amount pending outside domain",
            )
        )
    elif params.duty_mode == "tax":
        if params.tax_percent is None:
            tax = None
            warnings.append(
                PnlWarning(
                    code="tax_pending_manual",
                    message="Tax rate missing; amount pending manual attachment",
                )
            )
        else:
            tax = _percent_of_revenue(params.tax_percent, revenue)
    else:
        tax = _ZERO

    acquiring_percent = _ZERO
    acquiring_per_sale = _ZERO
    if params.acquiring_percent is not None:
        acquiring_percent = _percent_of_revenue(params.acquiring_percent, revenue)
    if params.acquiring_fee_per_sale is not None:
        acquiring_per_sale = round_money(params.acquiring_fee_per_sale * Decimal(sale_count))

    terminal = _ZERO
    if params.terminal_monthly is not None:
        terminal = _monthly_prorata(params.terminal_monthly, days=days, closed_at=closed_at)

    labor = _ZERO
    if params.labor_rate is not None and not params.missing_labor_rate:
        labor = round_money(params.labor_rate * Decimal(maintenance_count))

    route_fuel = _ZERO

    values: dict[str, Decimal | None] = {
        "rent_fixed": rent_fixed_money,
        "rent_percent": rent_percent_money,
        "patent": patent,
        "tax": tax,
        "acquiring_percent": acquiring_percent,
        "acquiring_per_sale": acquiring_per_sale,
        "terminal": terminal,
        "labor": labor,
        "route_fuel": route_fuel,
    }
    breakdown = tuple((key, values[key]) for key in OPEX_BREAKDOWN_KEYS)
    opex = round_money(
        sum(
            (amount for key, amount in breakdown if key != "tax" and amount is not None),
            _ZERO,
        )
    )
    return OpExComputation(breakdown=breakdown, opex=opex, warnings=tuple(warnings))
