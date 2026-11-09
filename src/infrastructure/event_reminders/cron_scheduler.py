from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from beartype import beartype


@beartype
def build_cron_expression(hours: tuple[int, ...]) -> str:
    """Build APScheduler crontab ``0 h1,h2,... * * *`` with hours sorted ascending."""
    if not hours:
        raise ValueError("hours must be non-empty")
    sorted_hours = sorted(hours)
    return f"0 {','.join(str(h) for h in sorted_hours)} * * *"


@runtime_checkable
class EventRemindersSchedulingBackend(Protocol):
    def add_cron_job(
        self,
        *,
        crontab: str,
        timezone: ZoneInfo,
        callback: Callable[[], None],
        job_id: str,
    ) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


@beartype
class ApschedulerEventRemindersBackend:
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
    ) -> None:
        self._scheduler.add_job(
            callback,
            CronTrigger.from_crontab(crontab, timezone=timezone),
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
class EventRemindersCronScheduler:
    enabled: bool
    hours: tuple[int, ...]
    timezone: ZoneInfo
    callback: Callable[[], None]
    backend: EventRemindersSchedulingBackend = field(
        default_factory=ApschedulerEventRemindersBackend,
    )

    @beartype
    def start(self) -> None:
        if not self.enabled:
            return
        crontab = build_cron_expression(self.hours)
        self.backend.add_cron_job(
            crontab=crontab,
            timezone=self.timezone,
            callback=self.callback,
            job_id="event_reminders_tick",
        )
        self.backend.start()

    @beartype
    def stop(self) -> None:
        self.backend.stop()
