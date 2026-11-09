from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.infrastructure.sales_ingest_watermark import (
    clamp_sales_ingest_cursor,
    compute_fetch_since,
)

_T0 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
_T2 = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
_NOW = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)


def test_clamp_without_holding_uses_batch_max() -> None:
    assert (
        clamp_sales_ingest_cursor(
            previous_cursor=_T0,
            success_occurred_at=(_T1, _T2),
            hold_at=None,
        )
        == _T2
    )


def test_clamp_only_holding_keeps_previous() -> None:
    assert (
        clamp_sales_ingest_cursor(
            previous_cursor=_T0,
            success_occurred_at=(),
            hold_at=_T1,
        )
        == _T0
    )


def test_clamp_uses_max_success_before_hold_at() -> None:
    assert (
        clamp_sales_ingest_cursor(
            previous_cursor=_T0,
            success_occurred_at=(_T1, _T2),
            hold_at=_T2,
        )
        == _T1
    )


def test_clamp_ignores_success_at_hold_at() -> None:
    assert (
        clamp_sales_ingest_cursor(
            previous_cursor=_T0,
            success_occurred_at=(_T1,),
            hold_at=_T1,
        )
        == _T0
    )


def test_compute_fetch_since_bootstrap_uses_lookback() -> None:
    assert compute_fetch_since(
        true_cursor=None,
        overlap_seconds=1800,
        initial_lookback=timedelta(days=7),
        now=_NOW,
    ) == _NOW - timedelta(days=7)


def test_compute_fetch_since_uses_cursor_minus_overlap() -> None:
    assert compute_fetch_since(
        true_cursor=_T2,
        overlap_seconds=1800,
        initial_lookback=timedelta(days=7),
        now=_NOW,
    ) == _T2 - timedelta(seconds=1800)


def test_compute_fetch_since_zero_overlap_equals_cursor() -> None:
    assert (
        compute_fetch_since(
            true_cursor=_T2,
            overlap_seconds=0,
            initial_lookback=timedelta(days=7),
            now=_NOW,
        )
        == _T2
    )
