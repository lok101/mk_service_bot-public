from __future__ import annotations

from src.application.outbox.handler_ids import VISIT_FORCE_NOTIFY_HANDLER_ID
from src.domain.service_visits import ServiceVisitForceNotifyRequested
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_visit_force_notify_handler,
    subscribe_visit_force_notify,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher


def test_visit_force_notify_handler_id() -> None:
    """happy: stable handler id."""
    assert VISIT_FORCE_NOTIFY_HANDLER_ID == "visit_force_notify"


def test_visit_force_notify_processor_does_not_subscribe() -> None:
    """happy: effects processor is registered; enqueue subscribe stays separate."""
    publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    processors = OutboxProcessorRegistry()
    register_visit_force_notify_handler(
        processors=processors,
        bot_token="0000000000:TEST",
        ops_chat_id=-100,
    )
    assert processors.is_registered(VISIT_FORCE_NOTIFY_HANDLER_ID)
    assert publisher.handler_ids_for(ServiceVisitForceNotifyRequested) == ()


def test_sm_publisher_subscribes_visit_force_notify_for_enqueue() -> None:
    """happy: SM subscribe-only — enqueue path without local processor."""
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    subscribe_visit_force_notify(publisher)
    assert not processors.is_registered(VISIT_FORCE_NOTIFY_HANDLER_ID)
    assert publisher.handler_ids_for(ServiceVisitForceNotifyRequested) == (
        VISIT_FORCE_NOTIFY_HANDLER_ID,
    )
