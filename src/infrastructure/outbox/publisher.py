from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from beartype import beartype

from src.application.machine_operations.ports import DomainEventPublisher, OutboxStore
from src.domain.events import DomainEvent
from src.infrastructure.outbox.serialization import event_to_outbox_document


@beartype
@dataclass
class OutboxDomainEventPublisher(DomainEventPublisher):
    store: OutboxStore
    _handler_ids_by_event_type: dict[type[object], list[str]] = field(
        default_factory=dict,
    )

    @beartype
    def subscribe(self, event_type: type[object], handler_id: str) -> None:
        self._handler_ids_by_event_type.setdefault(event_type, []).append(handler_id)

    @beartype
    def handler_ids_for(self, event_type: type[object]) -> tuple[str, ...]:
        return tuple(self._handler_ids_by_event_type.get(event_type, ()))

    @beartype
    def publish(self, event: DomainEvent) -> None:
        event_document = event_to_outbox_document(event)
        event_id = event.event_id.value
        not_before: datetime | None = getattr(event, "not_before", None)

        for event_type, handler_ids in self._handler_ids_by_event_type.items():
            if not isinstance(event, event_type):
                continue
            for handler_id in handler_ids:
                self.store.enqueue(
                    event_id=event_id,
                    handler_id=handler_id,
                    event_document=event_document,
                    not_before=not_before,
                )
