from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from beartype import beartype


@runtime_checkable
class MachinePnlMonthSchedulingBackend(Protocol):
    def add_interval_job(
        self,
        *,
        hours: int,
        timezone: ZoneInfo,
        callback: Callable[[], None],
        job_id: str,
        max_instances: int = 1,
    ) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


@beartype
class ApschedulerMachinePnlMonthBackend:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._started = False

    @beartype
    def add_interval_job(
        self,
        *,
        hours: int,
        timezone: ZoneInfo,
        callback: Callable[[], None],
        job_id: str,
        max_instances: int = 1,
    ) -> None:
        self._scheduler.add_job(
            callback,
            IntervalTrigger(hours=hours, timezone=timezone),
            id=job_id,
            replace_existing=True,
            max_instances=max_instances,
            next_run_time=datetime.now(timezone),
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
class MachinePnlMonthCronScheduler:
    enabled: bool
    interval_hours: int
    timezone: ZoneInfo
    callback: Callable[[], None]
    backend: MachinePnlMonthSchedulingBackend = field(
        default_factory=ApschedulerMachinePnlMonthBackend,
    )

    @beartype
    def start(self) -> None:
        if not self.enabled:
            return
        self.backend.add_interval_job(
            hours=self.interval_hours,
            timezone=self.timezone,
            callback=self.callback,
            job_id="machine_pnl_month_tick",
        )
        self.backend.start()

    @beartype
    def stop(self) -> None:
        self.backend.stop()
