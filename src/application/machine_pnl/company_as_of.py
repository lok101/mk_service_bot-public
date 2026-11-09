from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.inventory_reconciliation import MachineCompanyOccupancy
from src.application.machine_pnl.models import PnlWarning
from src.domain.machine_sales import MachineSale

COMPANY_MAJORITY_ASSUMPTION = "company_majority_assumption"
_MAJORITY_WARNING = PnlWarning(
    code=COMPANY_MAJORITY_ASSUMPTION,
    message="multiple Kit companies in month; recorded majority-revenue company",
)
_ZERO = Decimal("0")


def _inclusive_date_bounds(
    period_start: date,
    period_end: date,
    tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    opened_at = datetime.combine(period_start, time.min, tzinfo=tz) - timedelta(microseconds=1)
    closed_at = datetime.combine(period_end + timedelta(days=1), time.min, tzinfo=tz) - timedelta(
        microseconds=1,
    )
    return opened_at, closed_at


def _occupancy_intersects(
    occupancy: MachineCompanyOccupancy,
    *,
    opened_at: datetime,
    closed_at: datetime,
) -> bool:
    if occupancy.valid_from > closed_at:
        return False
    return occupancy.valid_to is None or occupancy.valid_to > opened_at


def _company_revenue(sales: Sequence[MachineSale], company_id: int) -> Decimal:
    total = _ZERO
    for sale in sales:
        if sale.company_id != company_id or sale.price is None:
            continue
        total += sale.price * sale.quantity
    return total


def _latest_valid_from(
    occupancies: Sequence[MachineCompanyOccupancy],
    company_id: int,
    tz: ZoneInfo,
) -> datetime:
    matching = [item.valid_from for item in occupancies if item.company_id == company_id]
    if not matching:
        return datetime.min.replace(tzinfo=tz)
    return max(matching)


@beartype
def resolve_month_company_id(
    *,
    sales: Sequence[MachineSale],
    occupancies: Sequence[MachineCompanyOccupancy],
    period_start: date,
    period_end: date,
    tz: ZoneInfo,
) -> tuple[int | None, tuple[PnlWarning, ...]]:
    company_ids = {sale.company_id for sale in sales if sale.company_id is not None}
    if len(company_ids) == 1:
        only = next(iter(company_ids))
        return only, ()

    opened_at, closed_at = _inclusive_date_bounds(period_start, period_end, tz)
    intersecting = tuple(
        occupancy
        for occupancy in occupancies
        if _occupancy_intersects(occupancy, opened_at=opened_at, closed_at=closed_at)
    )

    if not company_ids:
        if not intersecting:
            return None, ()
        if len(intersecting) == 1:
            return intersecting[0].company_id, ()
        chosen = max(intersecting, key=lambda occupancy: occupancy.valid_from)
        return chosen.company_id, (_MAJORITY_WARNING,)

    chosen_id = max(
        company_ids,
        key=lambda company_id: (
            _company_revenue(sales, company_id),
            _latest_valid_from(occupancies, company_id, tz),
        ),
    )
    return chosen_id, (_MAJORITY_WARNING,)
