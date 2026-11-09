from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from beartype import beartype

from src.domain.ids import EventId


@beartype
def daily_sales_demand_event_id(sales_day: date) -> EventId:
    return EventId(f"daily_sales_demand:{sales_day.isoformat()}")


@beartype
@dataclass(frozen=True, slots=True)
class DailySalesDemandRequested:
    event_id: EventId
    sales_day: date
    occurred_at: datetime
