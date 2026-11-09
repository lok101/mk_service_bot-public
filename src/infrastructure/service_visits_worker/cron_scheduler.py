from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class ServiceVisitsCronSpec:
    hour: int
    minute: int
    timezone: ZoneInfo


@beartype
def build_materialize_cron_spec(*, end_hour: int, timezone: ZoneInfo) -> ServiceVisitsCronSpec:
    return ServiceVisitsCronSpec(hour=end_hour, minute=0, timezone=timezone)


@runtime_checkable
class ServiceVisitsSchedulingBackend(Protocol):
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
class ApschedulerServiceVisitsBackend:
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
class ServiceVisitsCronScheduler:
    enabled: bool
    end_hour: int
    timezone: ZoneInfo
    callback: Callable[[], None]
    backend: ServiceVisitsSchedulingBackend = field(
        default_factory=ApschedulerServiceVisitsBackend,
    )

    @beartype
    def start(self) -> None:
        if not self.enabled:
            return
        spec = build_materialize_cron_spec(end_hour=self.end_hour, timezone=self.timezone)
        self.backend.add_cron_job(
            crontab=f"{spec.minute} {spec.hour} * * *",
            timezone=spec.timezone,
            callback=self.callback,
            job_id="service_visits_materialize",
        )
        self.backend.start()

    @beartype
    def stop(self) -> None:
        self.backend.stop()
