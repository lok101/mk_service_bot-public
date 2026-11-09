from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.events import DomainEvent
from src.domain.ids import EventId
from src.domain.micromarket_loading.post_visit_squeeze_event import (
    MicromarketPostVisitSqueezeRequested,
)

_logger = logging.getLogger(__name__)


@runtime_checkable
class PostVisitSqueezeEventPublisher(Protocol):
    """Narrow publish port; satisfied by OutboxDomainEventPublisher."""

    @beartype
    def publish(self, event: DomainEvent) -> None: ...


@beartype
@dataclass(slots=True)
class InMemoryEnqueuePostVisitSqueeze:
    """Test/dev stub: record enqueue without outbox."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    @beartype
    def enqueue(self, *, machine_code: str, inventory_id: str) -> None:
        self.calls.append((machine_code, inventory_id))
        _logger.info(
            "post_visit_squeeze_enqueued",
            extra={"machine_code": machine_code, "inventory_id": inventory_id},
        )


@beartype
@dataclass(frozen=True, slots=True)
class OutboxEnqueuePostVisitSqueeze:
    """Accept path: enqueue outbox command (ADR-0065); effects-worker drains."""

    publisher: PostVisitSqueezeEventPublisher
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    @beartype
    def enqueue(self, *, machine_code: str, inventory_id: str) -> None:
        event_id = EventId(f"micromarket_post_visit_squeeze:{machine_code}:{inventory_id}")
        self.publisher.publish(
            MicromarketPostVisitSqueezeRequested(
                event_id=event_id,
                machine_code=machine_code,
                inventory_id=inventory_id,
                occurred_at=self.clock(),
            ),
        )
        _logger.info(
            "post_visit_squeeze_enqueued",
            extra={
                "machine_code": machine_code,
                "inventory_id": inventory_id,
                "event_id": event_id.value,
            },
        )
