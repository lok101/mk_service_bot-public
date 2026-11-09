from __future__ import annotations

from beartype import beartype

from src.config.settings import (
    Settings,
    get_settings,
    validate_event_reminders_worker_settings,
)
from src.infrastructure.composition.event_reminders_worker_container import (
    EventRemindersWorkerContainer,
)
from src.infrastructure.composition.wiring.wire_event_reminders_worker import (
    wire_event_reminders_worker,
)


@beartype
def assemble_event_reminders_worker(
    settings: Settings | None = None,
) -> EventRemindersWorkerContainer:
    resolved = settings or get_settings()
    validate_event_reminders_worker_settings(resolved)
    return wire_event_reminders_worker(resolved)
