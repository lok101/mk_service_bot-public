from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.application.sales_monitoring.no_sales_stale import (
    is_ingest_cursor_fresh,
    is_sales_stale,
    visit_needed,
)

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_is_sales_stale_when_last_sale_none() -> None:
    """edge: нет last_sale → stale."""
    assert is_sales_stale(None, now=_NOW, stale_hours=24) is True


def test_is_sales_stale_when_older_than_threshold() -> None:
    """happy: last_sale старше N часов → stale."""
    last = _NOW - timedelta(hours=25)
    assert is_sales_stale(last, now=_NOW, stale_hours=24) is True


def test_is_sales_stale_when_within_threshold() -> None:
    """happy: свежая продажа → not stale."""
    last = _NOW - timedelta(hours=23)
    assert is_sales_stale(last, now=_NOW, stale_hours=24) is False


def test_ingest_cursor_not_fresh_when_none_or_lag() -> None:
    """edge: cursor None или lag > LAG → not fresh."""
    assert is_ingest_cursor_fresh(None, now=_NOW, max_lag_minutes=45) is False
    lagging = _NOW - timedelta(minutes=46)
    assert is_ingest_cursor_fresh(lagging, now=_NOW, max_lag_minutes=45) is False


def test_ingest_cursor_fresh_within_lag() -> None:
    """happy: cursor в пределах LAG."""
    cursor = _NOW - timedelta(minutes=44)
    assert is_ingest_cursor_fresh(cursor, now=_NOW, max_lag_minutes=45) is True


def test_visit_needed_respects_k_and_unknown_baseline() -> None:
    """happy+edge: K=0 → True; baseline None → True; low → False; high → True."""
    assert visit_needed(incident_open=True, baseline_avg=Decimal("1"), min_qty=Decimal("0")) is True
    assert visit_needed(incident_open=True, baseline_avg=None, min_qty=Decimal("100")) is True
    assert (
        visit_needed(incident_open=True, baseline_avg=Decimal("50"), min_qty=Decimal("100"))
        is False
    )
    assert (
        visit_needed(incident_open=True, baseline_avg=Decimal("100"), min_qty=Decimal("100"))
        is True
    )
    assert (
        visit_needed(incident_open=False, baseline_avg=Decimal("999"), min_qty=Decimal("0"))
        is False
    )
