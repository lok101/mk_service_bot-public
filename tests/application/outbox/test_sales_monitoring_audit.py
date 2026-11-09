from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from src.application.form_submissions import NonRetryableOutboxError
from src.application.outbox.sales_monitoring_audit import SalesMonitoringAuditHandler
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringYesterdayNoSales,
)
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

_MACHINE_ID = MachineId("vm-handler-01")
_NO_SALES_MACHINE_ID = MachineId("101")
_REPORT_DAY = date(2026, 7, 28)
_OCCURRED = datetime(2026, 7, 29, 6, 0, tzinfo=UTC)
_OPENED_AT = datetime(2026, 7, 27, 10, 0, tzinfo=UTC)
_CLEARED_AT = datetime(2026, 7, 28, 15, 0, tzinfo=UTC)
_LAST_SALE_AT = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
_SERVICED_AT = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)
_EVENT_ID = EventId(
    f"SalesMonitoringYesterdayNoSales:{_MACHINE_ID.value}:{_REPORT_DAY.isoformat()}"
)
_AUDIT_ID = f"SalesMonitoringYesterdayNoSales:{_MACHINE_ID.value}:{_REPORT_DAY.isoformat()}"
_NO_SALES_AUDIT_ID = f"no_sales:{_NO_SALES_MACHINE_ID.value}"


def _no_sales(
    *,
    assigned_technician_id: TechnicianId | None = None,
    assigned_technician_display: str | None = None,
    last_serviced_by_technician_id: TechnicianId | None = None,
    last_serviced_by_display: str | None = None,
    last_serviced_at: datetime | None = None,
) -> SalesMonitoringYesterdayNoSales:
    return SalesMonitoringYesterdayNoSales(
        event_id=_EVENT_ID,
        machine_id=_MACHINE_ID,
        report_day=_REPORT_DAY,
        occurred_at=_OCCURRED,
        assigned_technician_id=assigned_technician_id,
        assigned_technician_display=assigned_technician_display,
        last_serviced_by_technician_id=last_serviced_by_technician_id,
        last_serviced_by_display=last_serviced_by_display,
        last_serviced_at=last_serviced_at,
    )


def test_audit_handler_upserts_sales_finding() -> None:
    store = InMemorySalesMonitoringAuditStore()
    handler = SalesMonitoringAuditHandler(audit_store=store)

    asyncio.run(handler.process(_no_sales()))

    document = store.get(_AUDIT_ID)
    assert document is not None
    assert document["_id"] == _AUDIT_ID
    assert document["event_type"] == "SalesMonitoringYesterdayNoSales"
    assert document["machine_id"] == _MACHINE_ID.value


def test_audit_handler_double_upsert_idempotent() -> None:
    store = InMemorySalesMonitoringAuditStore()
    handler = SalesMonitoringAuditHandler(audit_store=store)
    event = _no_sales()

    asyncio.run(handler.process(event))
    asyncio.run(handler.process(event))

    assert len(store._documents) == 1
    assert store.get(_AUDIT_ID) is not None


def test_audit_persists_nullable_snapshot_fields() -> None:
    store = InMemorySalesMonitoringAuditStore()
    handler = SalesMonitoringAuditHandler(audit_store=store)

    asyncio.run(handler.process(_no_sales()))
    null_doc = store.get(_AUDIT_ID)
    assert null_doc is not None
    assert null_doc["assigned_technician_id"] is None
    assert null_doc["assigned_technician_display"] is None
    assert null_doc["last_serviced_by_technician_id"] is None
    assert null_doc["last_serviced_by_display"] is None
    assert null_doc["last_serviced_at"] is None

    asyncio.run(
        handler.process(
            _no_sales(
                assigned_technician_id=TechnicianId("tech-assigned"),
                assigned_technician_display="Закреплённый",
                last_serviced_by_technician_id=TechnicianId("tech-serviced"),
                last_serviced_by_display="Обслуживший",
                last_serviced_at=_SERVICED_AT,
            )
        )
    )
    filled = store.get(_AUDIT_ID)
    assert filled is not None
    assert filled["assigned_technician_id"] == "tech-assigned"
    assert filled["assigned_technician_display"] == "Закреплённый"
    assert filled["last_serviced_by_technician_id"] == "tech-serviced"
    assert filled["last_serviced_by_display"] == "Обслуживший"
    assert filled["last_serviced_at"] == _SERVICED_AT


def test_audit_handler_rejects_unsupported_event_non_retryable() -> None:
    store = InMemorySalesMonitoringAuditStore()
    handler = SalesMonitoringAuditHandler(audit_store=store)
    foreign = RevisionCompleted(
        event_id=EventId("event-foreign-1"),
        revision_id=RevisionId("rev-foreign-1"),
        technician_id=TechnicianId("tech-a"),
        machine_id=_MACHINE_ID,
        completed_at=_OCCURRED,
        occurred_at=_OCCURRED,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-1",
        form_token="token-1",
    )

    with pytest.raises(NonRetryableOutboxError):
        asyncio.run(handler.process(foreign))

    assert store.get(_AUDIT_ID) is None
    assert store.list_open_offline() == []


def _no_sales_stale_opened() -> SalesMonitoringNoSalesStaleOpened:
    return SalesMonitoringNoSalesStaleOpened(
        event_id=EventId(
            "sales-monitoring-no-sales-stale-opened:"
            f"{_NO_SALES_MACHINE_ID.value}:{_OPENED_AT.isoformat()}"
        ),
        machine_id=_NO_SALES_MACHINE_ID,
        opened_at=_OPENED_AT,
        occurred_at=_OPENED_AT,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-1"),
        assigned_technician_display="Иван",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def _no_sales_stale_cleared() -> SalesMonitoringNoSalesStaleCleared:
    opened = _no_sales_stale_opened()
    return SalesMonitoringNoSalesStaleCleared(
        event_id=EventId(
            "sales-monitoring-no-sales-stale-cleared:"
            f"{_NO_SALES_MACHINE_ID.value}:{_CLEARED_AT.isoformat()}"
        ),
        machine_id=_NO_SALES_MACHINE_ID,
        opened_event_id=opened.event_id,
        opened_at=_OPENED_AT,
        cleared_at=_CLEARED_AT,
        occurred_at=_CLEARED_AT,
        last_sale_at=_LAST_SALE_AT,
        assigned_technician_id=TechnicianId("tech-1"),
        assigned_technician_display="Иван",
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )


def test_audit_handler_upserts_no_sales_stale_open_then_cleared() -> None:
    """happy: Opened upserts sticky open; Cleared clears same _id."""
    store = InMemorySalesMonitoringAuditStore()
    handler = SalesMonitoringAuditHandler(audit_store=store)

    asyncio.run(handler.process(_no_sales_stale_opened()))
    document = store.get(_NO_SALES_AUDIT_ID)
    assert document is not None
    assert document["_id"] == "no_sales:101"
    assert document["status"] == "open"
    assert document["last_sale_at"] == _LAST_SALE_AT

    asyncio.run(handler.process(_no_sales_stale_cleared()))
    document = store.get(_NO_SALES_AUDIT_ID)
    assert document is not None
    assert document["status"] == "cleared"
    assert document["cleared_at"] == _CLEARED_AT
    assert store.list_open_no_sales() == []
