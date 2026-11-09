from __future__ import annotations

from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)
from tests.infrastructure.composition.test_sales_monitoring_audit_ownership import (
    SALES_MONITORING_AUDIT_EVENT_TYPES,
)

from src.application.outbox.handler_ids import SALES_MONITORING_AUDIT_HANDLER_ID
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher


def test_app_skips_sales_monitoring_audit_handler_after_single_owner_cutover() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = _minimal_outbox_handler_deps(include_post_accountability=False)

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
    )

    assert processors.is_registered(SALES_MONITORING_AUDIT_HANDLER_ID) is False
    for event_type in SALES_MONITORING_AUDIT_EVENT_TYPES:
        assert SALES_MONITORING_AUDIT_HANDLER_ID not in publisher.handler_ids_for(
            event_type,
        )
