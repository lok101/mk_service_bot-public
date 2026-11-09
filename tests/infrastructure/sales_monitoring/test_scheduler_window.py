from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.infrastructure.sales_monitoring.cron_scheduler import (
    SalesMonitoringCronScheduler,
    is_within_offline_poll_window,
)

_TZ = ZoneInfo("Asia/Yekaterinburg")


def test_offline_poll_skipped_outside_hour_window() -> None:
    now = datetime(2026, 7, 29, 23, 0, tzinfo=_TZ)
    assert is_within_offline_poll_window(now, from_hour=8, to_hour=22) is False

    calls: list[str] = []
    scheduler = SalesMonitoringCronScheduler(
        enabled=True,
        timezone=_TZ,
        report_compare_cron="0 8 * * *",
        report_today_cron="0 15 * * *",
        offline_poll_interval_minutes=60,
        offline_poll_from_hour=8,
        offline_poll_to_hour=22,
        no_sales_eval_interval_minutes=60,
        compare_callback=lambda: calls.append("compare"),
        today_callback=lambda: calls.append("today"),
        offline_callback=lambda: calls.append("offline"),
        no_sales_stale_callback=lambda: calls.append("stale"),
        clock=lambda: now,
    )
    scheduler.run_offline_poll_tick()
    assert calls == []


def test_offline_poll_runs_inside_hour_window() -> None:
    now = datetime(2026, 7, 29, 10, 0, tzinfo=_TZ)
    assert is_within_offline_poll_window(now, from_hour=8, to_hour=22) is True

    calls: list[str] = []
    scheduler = SalesMonitoringCronScheduler(
        enabled=True,
        timezone=_TZ,
        report_compare_cron="0 8 * * *",
        report_today_cron="0 15 * * *",
        offline_poll_interval_minutes=60,
        offline_poll_from_hour=8,
        offline_poll_to_hour=22,
        no_sales_eval_interval_minutes=60,
        compare_callback=lambda: calls.append("compare"),
        today_callback=lambda: calls.append("today"),
        offline_callback=lambda: calls.append("offline"),
        no_sales_stale_callback=lambda: calls.append("stale"),
        clock=lambda: now,
    )
    scheduler.run_offline_poll_tick()
    assert calls == ["offline"]


def test_scheduler_start_noop_when_disabled() -> None:
    started: list[bool] = []

    class _Backend:
        def add_cron_job(
            self,
            *,
            crontab: str,
            timezone: ZoneInfo,
            callback: object,
            job_id: str,
        ) -> None:
            raise AssertionError("add_cron_job must not be called when disabled")

        def add_interval_job(
            self,
            *,
            minutes: int,
            callback: object,
            job_id: str,
        ) -> None:
            raise AssertionError("add_interval_job must not be called when disabled")

        def start(self) -> None:
            started.append(True)

        def stop(self) -> None:
            return None

    scheduler = SalesMonitoringCronScheduler(
        enabled=False,
        timezone=_TZ,
        report_compare_cron="0 8 * * *",
        report_today_cron="0 15 * * *",
        offline_poll_interval_minutes=60,
        offline_poll_from_hour=8,
        offline_poll_to_hour=22,
        no_sales_eval_interval_minutes=60,
        compare_callback=lambda: None,
        today_callback=lambda: None,
        offline_callback=lambda: None,
        no_sales_stale_callback=lambda: None,
        backend=_Backend(),
    )
    scheduler.start()
    assert started == []
