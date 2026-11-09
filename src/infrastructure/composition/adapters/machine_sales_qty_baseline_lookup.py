from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.sales_monitoring.qty_baseline import like_day_qty_baseline_avg
from src.domain.calendar import calendar_day_in_timezone
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale


@beartype
@dataclass(frozen=True, slots=True)
class MachineSalesStoreQtyBaselineLookup:
    sales: MachineSalesStore
    timezone: ZoneInfo
    days_for_average: int
    baseline_min_points: int
    baseline_winsorize_min_points: int
    baseline_winsorize_percent: int

    @beartype
    def baseline_avg_qty(
        self,
        *,
        machine_id: MachineId,
        as_of_day: date,
    ) -> Decimal | None:
        opened_at = datetime.combine(
            as_of_day - timedelta(days=self.days_for_average),
            time.min,
            tzinfo=self.timezone,
        )
        closed_at = datetime.combine(as_of_day, time.min, tzinfo=self.timezone)
        rows: tuple[MachineSale, ...] = self.sales.find_in_window(
            machine_id,
            opened_at=opened_at,
            closed_at=closed_at,
        )
        by_day: dict[date, list[MachineSale]] = defaultdict(list)
        for sale in rows:
            by_day[calendar_day_in_timezone(sale.occurred_at, self.timezone)].append(sale)
        return like_day_qty_baseline_avg(
            report_day=as_of_day,
            by_day=by_day,
            days_for_average=self.days_for_average,
            baseline_min_points=self.baseline_min_points,
            baseline_winsorize_min_points=self.baseline_winsorize_min_points,
            baseline_winsorize_percent=self.baseline_winsorize_percent,
        )
