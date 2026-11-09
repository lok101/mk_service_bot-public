from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from beartype import beartype

from src.config.settings import Settings
from src.infrastructure.event_reminders.worker_runtime import EventRemindersWorkerRuntime


@beartype
@dataclass
class EventRemindersWorkerContainer:
    """Standalone composition root for event-reminders-worker (no Mongo, no AppContainer)."""

    runtime: EventRemindersWorkerRuntime
    extra_closers: tuple[Callable[[], None], ...] = field(default_factory=tuple)

    @classmethod
    @beartype
    def from_settings(cls, settings: Settings | None = None) -> EventRemindersWorkerContainer:
        from src.infrastructure.composition.wiring.assemble_event_reminders_worker import (
            assemble_event_reminders_worker,
        )

        return assemble_event_reminders_worker(settings)

    @beartype
    async def run(self) -> None:
        await self.runtime.run()

    @beartype
    def request_shutdown(self) -> None:
        self.runtime.request_shutdown()

    @beartype
    def close(self) -> None:
        for closer in self.extra_closers:
            closer()
