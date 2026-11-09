from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from beartype import beartype


@runtime_checkable
class CronSchedulingBackend(Protocol):
    def add_daily_job(
        self,
        *,
        hour: int,
        timezone: ZoneInfo,
        callback: Callable[[], None],
    ) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


@beartype
class ApschedulerCronBackend:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler()
        self._started = False

    @beartype
    def add_daily_job(
        self,
        *,
        hour: int,
        timezone: ZoneInfo,
        callback: Callable[[], None],
    ) -> None:
        self._scheduler.add_job(
            callback,
            CronTrigger(hour=hour, minute=0, timezone=timezone),
            id="matrix_daily_deploy",
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
class MatrixCronScheduler:
    enabled: bool
    hour: int
    timezone: ZoneInfo
    callback: Callable[[], None]
    backend: CronSchedulingBackend = field(default_factory=ApschedulerCronBackend)

    @beartype
    def start(self) -> None:
        if not self.enabled:
            return
        self.backend.add_daily_job(
            hour=self.hour,
            timezone=self.timezone,
            callback=self.callback,
        )
        self.backend.start()

    @beartype
    def stop(self) -> None:
        self.backend.stop()
