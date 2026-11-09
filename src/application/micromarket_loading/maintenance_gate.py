from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from beartype import beartype

from src.domain.calendar import operational_day, operational_day_window
from src.domain.micromarket_loading.events import (
    MicromarketInventoryAccepted,
    MicromarketStockEvent,
)


@beartype
def has_micromarket_inventory_in_operational_day(
    events: Sequence[MicromarketStockEvent],
    *,
    checked_at: datetime,
    timezone: ZoneInfo,
    day_end_hour: int,
) -> bool:
    ops_day = operational_day(checked_at, timezone, day_end_hour)
    start, end = operational_day_window(ops_day, timezone, day_end_hour)
    for event in events:
        if isinstance(event, MicromarketInventoryAccepted) and start <= event.as_of < end:
            return True
    return False


@beartype
def last_micromarket_inventory_quantities_for_operational_day(
    events: Sequence[MicromarketStockEvent],
    *,
    checked_at: datetime,
    timezone: ZoneInfo,
    day_end_hour: int,
) -> Mapping[str, Decimal]:
    ops_day = operational_day(checked_at, timezone, day_end_hour)
    start, end = operational_day_window(ops_day, timezone, day_end_hour)
    last: MicromarketInventoryAccepted | None = None
    for event in events:
        if isinstance(event, MicromarketInventoryAccepted) and start <= event.as_of < end:
            last = event
    if last is None:
        return {}
    return dict(last.quantities)
