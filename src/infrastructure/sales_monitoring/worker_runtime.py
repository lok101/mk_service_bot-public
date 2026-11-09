from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from beartype import beartype

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class SalesMonitoringWorkerStatusRepository(Protocol):
    def record_heartbeat(self, *, at: str, enabled: bool) -> None: ...


@runtime_checkable
class SalesMonitoringWorkerScheduler(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


@runtime_checkable
class SalesMonitoringWorkerClock(Protocol):
    def now_utc_iso(self) -> str: ...


@beartype
@dataclass(slots=True)
class SalesMonitoringWorkerRuntime:
    enabled: bool
    status_repository: SalesMonitoringWorkerStatusRepository
    scheduler: SalesMonitoringWorkerScheduler
    clock: SalesMonitoringWorkerClock
    heartbeat_interval_seconds: float = 60.0
    _shutdown_requested: bool = field(default=False, init=False, repr=False)
    _shutdown_event: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)

    @beartype
    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        self._shutdown_event.set()

    @property
    @beartype
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    @beartype
    async def run(self) -> None:
        if self.enabled:
            self.scheduler.start()
        try:
            while not self.shutdown_requested:
                try:
                    await asyncio.to_thread(
                        self.status_repository.record_heartbeat,
                        at=self.clock.now_utc_iso(),
                        enabled=self.enabled,
                    )
                except Exception:
                    _LOGGER.exception("sales_monitoring_worker_heartbeat_failed")
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.heartbeat_interval_seconds,
                    )
                except TimeoutError:
                    continue
        finally:
            self.scheduler.stop()
