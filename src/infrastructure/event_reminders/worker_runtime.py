from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from beartype import beartype


@runtime_checkable
class EventRemindersWorkerScheduler(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


@beartype
@dataclass(slots=True)
class EventRemindersWorkerRuntime:
    """Idle/cron loop without Mongo heartbeat or status repository."""

    enabled: bool
    scheduler: EventRemindersWorkerScheduler
    idle_poll_seconds: float = 60.0
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
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.idle_poll_seconds,
                    )
                except TimeoutError:
                    continue
        finally:
            self.scheduler.stop()
