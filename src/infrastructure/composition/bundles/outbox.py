from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.settlement_publisher import SettlementOutboxPublisher
from src.infrastructure.outbox.worker import OutboxWorker


@beartype
@dataclass(frozen=True, slots=True)
class OutboxBundle:
    publisher: OutboxDomainEventPublisher
    processors: OutboxProcessorRegistry
    worker: OutboxWorker
    settlement_publisher: SettlementOutboxPublisher
