"""B96 / LOK-130: single owner sales_monitoring_audit after fragment 02.

App: register_outbox_handlers does not register handler.
Worker: _register_sales_monitoring_audit in wire_sales_monitoring_worker.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)

from src.application.outbox.handler_ids import SALES_MONITORING_AUDIT_HANDLER_ID
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.composition.wiring.sales_monitoring_worker_adapters import (
    _register_sales_monitoring_audit,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.memory import OUTBOX_STATUS_PENDING
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.serialization import event_to_outbox_document
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

SALES_MONITORING_AUDIT_EVENT_TYPES = (
    SalesMonitoringYesterdayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringTodayNoSales,
    SalesMonitoringOfflineOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringNoSalesStaleCleared,
)


def test_single_owner_only_worker_registers_sales_monitoring_audit() -> None:
    audit_store = InMemorySalesMonitoringAuditStore()

    app_processors = OutboxProcessorRegistry()
    app_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    register_outbox_handlers(
        publisher=app_publisher,
        processors=app_processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=False),
    )
    assert app_processors.is_registered(SALES_MONITORING_AUDIT_HANDLER_ID) is False

    worker_processors = OutboxProcessorRegistry()
    worker_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    _register_sales_monitoring_audit(
        publisher=worker_publisher,
        processors=worker_processors,
        audit_store=audit_store,
    )
    assert worker_processors.is_registered(SALES_MONITORING_AUDIT_HANDLER_ID)
    for event_type in SALES_MONITORING_AUDIT_EVENT_TYPES:
        assert SALES_MONITORING_AUDIT_HANDLER_ID in worker_publisher.handler_ids_for(
            event_type,
        )


def test_app_outbox_worker_does_not_claim_sales_monitoring_audit_after_cutover() -> None:
    store = InMemoryOutboxStore()
    processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=OutboxDomainEventPublisher(store=store),
        processors=processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=False),
    )
    machine_id = MachineId("vm-audit-skip-01")
    report_day = date(2026, 7, 28)
    event = SalesMonitoringYesterdayNoSales(
        event_id=EventId(
            f"SalesMonitoringYesterdayNoSales:{machine_id.value}:{report_day.isoformat()}",
        ),
        machine_id=machine_id,
        report_day=report_day,
        occurred_at=datetime(2026, 7, 29, 8, 0, tzinfo=UTC),
        assigned_technician_id=TechnicianId("tech-audit-skip"),
        assigned_technician_display="Техник",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    store.enqueue(
        event_id=event.event_id.value,
        handler_id=SALES_MONITORING_AUDIT_HANDLER_ID,
        event_document=event_to_outbox_document(event),
    )
    asyncio.run(OutboxWorker(store=store, processors=processors).process_batch())
    entry = next(
        e for e in store._entries.values() if e["handler_id"] == SALES_MONITORING_AUDIT_HANDLER_ID
    )
    assert entry["status"] == OUTBOX_STATUS_PENDING
    assert entry["attempts"] == 0
    assert entry.get("claim_id") is None
    assert processors.is_registered(SALES_MONITORING_AUDIT_HANDLER_ID) is False


def test_single_owner_cutover_no_app_fallback_when_worker_disabled() -> None:
    """Rollback требует revert deploy с app registration, не env toggle alone."""
    processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=OutboxDomainEventPublisher(store=InMemoryOutboxStore()),
        processors=processors,
        deps=_minimal_outbox_handler_deps(include_post_accountability=False),
    )
    assert processors.is_registered(SALES_MONITORING_AUDIT_HANDLER_ID) is False
