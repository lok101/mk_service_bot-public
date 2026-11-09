from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from beartype import beartype


@runtime_checkable
class DailySalesDemandSchedulingBackend(Protocol):
    def add_cron_job(
        self,
        *,
        crontab: str,
        timezone: ZoneInfo,
        callback: Callable[[], None],
        job_id: str,
        max_instances: int = 1,
    ) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


@beartype
class ApschedulerDailySalesDemandBackend:
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
class DailySalesDemandCronScheduler:
    enabled: bool
    cron_hour: int
    timezone: ZoneInfo
    callback: Callable[[], None]
    backend: DailySalesDemandSchedulingBackend = field(
        default_factory=ApschedulerDailySalesDemandBackend,
    )

    @beartype
    def start(self) -> None:
        if not self.enabled:
            return
        self.backend.add_cron_job(
            crontab=f"0 {self.cron_hour} * * *",
            timezone=self.timezone,
            callback=self.callback,
            job_id="daily_sales_demand_enqueue",
        )
        self.backend.start()

    @beartype
    def stop(self) -> None:
        self.backend.stop()
