from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.application.sales_monitoring.incident_panel import (
    OFFLINE_CHECK_ABSENT,
    history_window,
    live_group,
    live_row_note,
    open_no_sales_session_id,
    task_suppressed_reason,
)


def test_open_no_sales_session_id_prefers_opened_event_id() -> None:
    assert (
        open_no_sales_session_id(
            {
                "status": "open",
                "opened_event_id": "opened-1",
                "event_id": "other-event",
            }
        )
        == "opened-1"
    )


def test_open_no_sales_session_id_uses_event_id_when_opened_field_missing() -> None:
    assert (
        open_no_sales_session_id(
            {
                "status": "open",
                "event_id": "sales-monitoring-no-sales-stale-opened:188:2026-09-19",
            }
        )
        == "sales-monitoring-no-sales-stale-opened:188:2026-09-19"
    )


def test_open_no_sales_session_id_ignores_event_id_on_cleared() -> None:
    assert (
        open_no_sales_session_id(
            {
                "status": "cleared",
                "event_id": "sales-monitoring-no-sales-stale-cleared:188:2026-09-20",
            }
        )
        is None
    )


def test_live_panel_groups_engineer_above_muted() -> None:
    assert live_group(engineer=True, muted=True) == "engineer"
    assert live_group(engineer=False, muted=True) == "muted"
    assert live_group(engineer=False, muted=False) == "problem"


def test_task_suppressed_reason_prefers_engineer_over_mute() -> None:
    assert (
        task_suppressed_reason(
            engineer=True,
            muted=True,
            visit_allowed=False,
            turnover_suppressed=True,
        )
        == "waiting_engineer"
    )
    assert (
        task_suppressed_reason(
            engineer=False,
            muted=False,
            visit_allowed=False,
            turnover_suppressed=True,
        )
        == "visit_flag"
    )
    assert (
        task_suppressed_reason(
            engineer=False,
            muted=False,
            visit_allowed=True,
            turnover_suppressed=True,
        )
        == "turnover"
    )
    assert (
        task_suppressed_reason(
            engineer=False,
            muted=False,
            visit_allowed=True,
            turnover_suppressed=False,
        )
        is None
    )


def test_live_row_for_micro_market_states_offline_check_missing() -> None:
    assert live_row_note(kind="micro_market", vending_offline=False) == OFFLINE_CHECK_ABSENT
    assert live_row_note(kind="snack", vending_offline=True) == "не на связи"
    assert live_row_note(kind="micro_market", vending_offline=True) == OFFLINE_CHECK_ABSENT


def test_history_includes_row_opened_in_period() -> None:
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    start, end = history_window(now=now, raw_from=None, raw_to=None)
    opened = now - timedelta(days=6)
    assert start <= opened <= end
    assert opened - timedelta(days=1) < start
