from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from beartype import beartype

from src.application.outbox.ports import OutboxEventDeserializer
from src.domain.events import DomainEvent
from src.infrastructure.outbox.serialization import event_from_outbox_document


@beartype
@dataclass(frozen=True, slots=True)
class OutboxEventDeserializerAdapter(OutboxEventDeserializer):
    def from_document(self, document: dict[str, Any]) -> DomainEvent:
        return event_from_outbox_document(document)
