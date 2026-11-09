from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from beartype import beartype


@beartype
def is_within_offline_poll_window(
    now: datetime,
    *,
    from_hour: int,
    to_hour: int,
) -> bool:
    return from_hour <= now.hour < to_hour


@runtime_checkable
class SalesMonitoringSchedulingBackend(Protocol):
    def add_cron_job(
        self,
        *,
        crontab: str,
        timezone: ZoneInfo,
        callback: Callable[[], None],
        job_id: str,
        max_instances: int = 1,
    ) -> None: ...

    def add_interval_job(
        self,
        *,
        minutes: int,
        callback: Callable[[], None],
        job_id: str,
    ) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


@beartype
class ApschedulerSalesMonitoringBackend:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._started = False

    @beartype
    def add_cron_job(
        self,
        *,
        crontab: str,
        timezone: ZoneInfo,
        callback: Callable[[], None],
        job_id: str,
        max_instances: int = 1,
    ) -> None:
        self._scheduler.add_job(
            callback,
            CronTrigger.from_crontab(crontab, timezone=timezone),
            id=job_id,
            replace_existing=True,
            max_instances=max_instances,
        )

    @beartype
    def add_interval_job(
        self,
        *,
        minutes: int,
        callback: Callable[[], None],
        job_id: str,
    ) -> None:
        self._scheduler.add_job(
            callback,
            IntervalTrigger(minutes=minutes),
            id=job_id,
            replace_existing=True,
        )

    @beartype
    def start(self) -> None:
        if not self._started:
            self._scheduler.start()
            self._started = True

    @beartype
    def stop(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False


@beartype
@dataclass(slots=True)
class SalesMonitoringCronScheduler:
    enabled: bool
    timezone: ZoneInfo
    report_compare_cron: str
    report_today_cron: str
    offline_poll_interval_minutes: int
    offline_poll_from_hour: int
    offline_poll_to_hour: int
    no_sales_eval_interval_minutes: int
    compare_callback: Callable[[], None]
    today_callback: Callable[[], None]
    offline_callback: Callable[[], None]
    no_sales_stale_callback: Callable[[], None]
    backend: SalesMonitoringSchedulingBackend = field(
        default_factory=ApschedulerSalesMonitoringBackend,
    )
    clock: Callable[[], datetime] | None = None
    sales_sheet_export_enabled: bool = False
    sales_sheet_export_cron: str = "0 1 * * *"
    export_callback: Callable[[], None] | None = None
    status_board_cron: str = "0 8 * * *"
    status_board_rotate_callback: Callable[[], None] = field(default_factory=lambda: lambda: None)

    @beartype
    def run_offline_poll_tick(self) -> None:
        now = self.clock() if self.clock is not None else datetime.now(self.timezone)
        if not is_within_offline_poll_window(
            now,
            from_hour=self.offline_poll_from_hour,
            to_hour=self.offline_poll_to_hour,
        ):
            return
        self.offline_callback()

    @beartype
    def run_no_sales_stale_eval_tick(self) -> None:
        now = self.clock() if self.clock is not None else datetime.now(self.timezone)
        if not is_within_offline_poll_window(
            now,
            from_hour=self.offline_poll_from_hour,
            to_hour=self.offline_poll_to_hour,
        ):
            return
        self.no_sales_stale_callback()

    @beartype
    def start(self) -> None:
        if not self.enabled:
            return
        self.backend.add_cron_job(
            crontab=self.report_compare_cron,
            timezone=self.timezone,
            callback=self.compare_callback,
            job_id="sales_monitoring_report_compare",
        )
        self.backend.add_cron_job(
            crontab=self.report_today_cron,
            timezone=self.timezone,
            callback=self.today_callback,
            job_id="sales_monitoring_report_today",
        )
        if self.sales_sheet_export_enabled and self.export_callback is not None:
            self.backend.add_cron_job(
                crontab=self.sales_sheet_export_cron,
                timezone=self.timezone,
                callback=self.export_callback,
                job_id="sales_monitoring_sales_sheet_export",
                max_instances=1,
            )
        self.backend.add_interval_job(
            minutes=self.offline_poll_interval_minutes,
            callback=self.run_offline_poll_tick,
            job_id="sales_monitoring_offline_poll",
        )
        self.backend.add_interval_job(
            minutes=self.no_sales_eval_interval_minutes,
            callback=self.run_no_sales_stale_eval_tick,
            job_id="sales_monitoring_no_sales_stale_eval",
        )
        self.backend.add_cron_job(
            crontab=self.status_board_cron,
            timezone=self.timezone,
            callback=self.status_board_rotate_callback,
            job_id="sales_monitoring_no_sales_status_board",
        )
        self.backend.start()

    @beartype
    def stop(self) -> None:
        self.backend.stop()
