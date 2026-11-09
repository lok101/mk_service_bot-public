from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field

from beartype import beartype

from src.infrastructure.outbox.worker import OutboxWorker

_LOGGER = logging.getLogger(__name__)


@beartype
@dataclass(slots=True)
class VisitPhotoGroupingWorkerRuntime:
    """Heartbeat loop; optional outbox drain when processing is enabled."""

    enabled: bool
    outbox_worker: OutboxWorker | None = None
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
        drain_task: asyncio.Task[None] | None = None
        if self.enabled and self.outbox_worker is not None:
            drain_task = asyncio.create_task(
                self.outbox_worker.run_until_shutdown(self._shutdown_event),
                name="visit-photo-grouping-outbox",
            )
        try:
            while not self.shutdown_requested:
                _LOGGER.info(
                    "visit_photo_grouping_worker_heartbeat enabled=%s",
                    self.enabled,
                )
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.heartbeat_interval_seconds,
                    )
                except TimeoutError:
                    continue
        finally:
            self._shutdown_event.set()
            if drain_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await drain_task
