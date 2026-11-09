from __future__ import annotations

from datetime import datetime, timedelta

from beartype import beartype


@beartype
def clamp_sales_ingest_cursor(
    *,
    previous_cursor: datetime | None,
    success_occurred_at: tuple[datetime, ...],
    hold_at: datetime | None,
) -> datetime | None:
    if hold_at is None:
        if not success_occurred_at:
            return previous_cursor
        return max(success_occurred_at)
    before = tuple(ts for ts in success_occurred_at if ts < hold_at)
    if not before:
        return previous_cursor
    return max(before)


@beartype
def compute_fetch_since(
    *,
    true_cursor: datetime | None,
    overlap_seconds: int,
    initial_lookback: timedelta,
    now: datetime,
) -> datetime:
    if true_cursor is None:
        return now - initial_lookback
    return true_cursor - timedelta(seconds=overlap_seconds)
