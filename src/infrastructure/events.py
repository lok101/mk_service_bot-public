from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from beartype import beartype

from src.application.machine_operations.ports import DomainEventPublisher
from src.domain.events import DomainEvent

DomainEventHandler = Callable[[object], None]


@beartype
@dataclass(frozen=True, slots=True)
class SyncDomainEventPublisher(DomainEventPublisher):
    handlers_by_event_type: dict[type[object], list[DomainEventHandler]] = field(
        default_factory=dict,
    )

    @beartype
    def subscribe(
        self,
        event_type: type[object],
        handler: DomainEventHandler,
    ) -> None:
        self.handlers_by_event_type.setdefault(event_type, []).append(handler)

    @beartype
    def publish(self, event: DomainEvent) -> None:
        for event_type, handlers in self.handlers_by_event_type.items():
            if not isinstance(event, event_type):
                continue
            for handler in handlers:
                handler(event)
