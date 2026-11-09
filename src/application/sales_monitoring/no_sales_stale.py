from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from beartype import beartype


@beartype
def is_sales_stale(
    last_sale_at: datetime | None,
    *,
    now: datetime,
    stale_hours: int,
) -> bool:
    if last_sale_at is None:
        return True
    return (now - last_sale_at) >= timedelta(hours=stale_hours)


@beartype
def is_ingest_cursor_fresh(
    cursor: datetime | None,
    *,
    now: datetime,
    max_lag_minutes: int,
) -> bool:
    if cursor is None:
        return False
    return (now - cursor) <= timedelta(minutes=max_lag_minutes)


@beartype
def visit_needed(
    *,
    incident_open: bool,
    baseline_avg: Decimal | None,
    min_qty: Decimal,
) -> bool:
    if not incident_open:
        return False
    if min_qty <= 0:
        return True
    if baseline_avg is None:
        return True
    return baseline_avg >= min_qty
