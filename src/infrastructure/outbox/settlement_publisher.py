from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from beartype import beartype

from src.application.machine_operations.ports import OutboxStore


@beartype
@dataclass(slots=True)
class SettlementOutboxPublisher:
    """Legacy settlement outbox channel (v1). Retained as no-op for wiring compatibility."""

    store: OutboxStore
    _handler_ids_by_event_type: dict[type[object], list[str]] = field(
        default_factory=dict,
    )

    @beartype
    def subscribe(self, event_type: type[object], handler_id: str) -> None:
        self._handler_ids_by_event_type.setdefault(event_type, []).append(handler_id)

    @beartype
    def subscribed_handler_ids(self, event: Any) -> tuple[str, ...]:
        return ()

    @beartype
    def publish_enqueued_handlers(self, event: Any) -> tuple[str, ...]:
        return ()

    @beartype
    def publish(self, event: Any) -> None:
        return None
