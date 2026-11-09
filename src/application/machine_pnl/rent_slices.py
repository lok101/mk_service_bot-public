from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.errors import RentTermsPending
from src.application.machine_pnl.money import round_money
from src.application.machine_pnl.opex import period_days
from src.domain.ids import MachineId

_ZERO = Decimal("0.00")


@beartype
@dataclass(frozen=True, slots=True)
class LocationRentOccupancy:
    location_id: str
    machine_id: MachineId
    installed_at: datetime
    removed_at: datetime | None
    rent_monthly: Decimal | None
    rent_percent: Decimal | None


@beartype
@dataclass(frozen=True, slots=True)
class RentSlicesSum:
    rent_fixed: Decimal
    rent_percent: Decimal


def _monthly_prorata(monthly: Decimal, *, days: int, closed_at: datetime) -> Decimal:
    month_days = calendar.monthrange(closed_at.year, closed_at.month)[1]
    return round_money(monthly * Decimal(days) / Decimal(month_days))


@beartype
def sum_rent_slices(
    *,
    occupancies: tuple[LocationRentOccupancy, ...],
    opened_at: datetime,
    closed_at: datetime,
    revenue: Decimal,
) -> RentSlicesSum:
    period_days_full = period_days(opened_at=opened_at, closed_at=closed_at)
    rent_fixed = _ZERO
    rent_percent_money = _ZERO
    intersecting = False

    for occupancy in occupancies:
        slice_start = max(opened_at, occupancy.installed_at)
        slice_end = min(closed_at, occupancy.removed_at or closed_at)
        if not (slice_start < slice_end):
            continue
        intersecting = True
        if occupancy.rent_monthly is None:
            raise RentTermsPending()
        days_i = period_days(opened_at=slice_start, closed_at=slice_end)
        rent_fixed = round_money(
            rent_fixed
            + _monthly_prorata(
                occupancy.rent_monthly,
                days=days_i,
                closed_at=slice_end,
            )
        )
        if occupancy.rent_percent is not None:
            rent_percent_money = round_money(
                rent_percent_money
                + (occupancy.rent_percent / Decimal("100"))
                * revenue
                * (Decimal(days_i) / Decimal(period_days_full))
            )

    if not intersecting:
        raise RentTermsPending()

    return RentSlicesSum(rent_fixed=rent_fixed, rent_percent=rent_percent_money)
