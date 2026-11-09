from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pymongo.database import Database

from src.application.outbox.handler_ids import SALES_MONITORING_AUDIT_HANDLER_ID
from src.application.outbox.sales_monitoring_audit import SalesMonitoringAuditHandler
from src.domain.ids import EventId, MachineId
from src.domain.machine_sales import MachineSale
from src.domain.sales_monitoring.events import (
    SalesMonitoringOfflineOpened,
    SalesMonitoringYesterdayNoSales,
)
from src.infrastructure.mongodb.machine_sales import MongoMachineSalesStore
from src.infrastructure.mongodb.sales_monitoring_audit import MongoSalesMonitoringAuditStore
from src.infrastructure.outbox.mongo import MongoOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.worker import OutboxWorker

pytestmark = pytest.mark.integration

_MACHINE_ID = MachineId("vm-sm-audit-01")
_REPORT_DAY = date(2026, 7, 28)
_OCCURRED = datetime(2026, 7, 29, 6, 0, tzinfo=UTC)
_SALE_AT = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
_WINDOW_OPEN = datetime(2026, 7, 28, 0, 0, tzinfo=UTC)
_OPENED_AT = datetime(2026, 7, 27, 10, 15, 30, tzinfo=UTC)
_SALES_AUDIT_ID = f"SalesMonitoringYesterdayNoSales:{_MACHINE_ID.value}:{_REPORT_DAY.isoformat()}"
_OFFLINE_AUDIT_ID = f"offline:{_MACHINE_ID.value}"
_SALE_PRICE = Decimal("150.00")


def _build_audit_pipeline(
    mongo_database: Database,
) -> tuple[
    OutboxDomainEventPublisher,
    OutboxWorker,
    Database,
]:
    outbox_store = MongoOutboxStore.from_collection(
        mongo_database["domain_event_outbox"],
        max_attempts=3,
    )
    audit_store = MongoSalesMonitoringAuditStore.from_collection(
        mongo_database["sales_monitoring_audit"],
    )
    publisher = OutboxDomainEventPublisher(store=outbox_store)
    publisher.subscribe(SalesMonitoringYesterdayNoSales, SALES_MONITORING_AUDIT_HANDLER_ID)
    publisher.subscribe(SalesMonitoringOfflineOpened, SALES_MONITORING_AUDIT_HANDLER_ID)

    handler = SalesMonitoringAuditHandler(audit_store=audit_store)
    processors = OutboxProcessorRegistry()
    processors.register(SALES_MONITORING_AUDIT_HANDLER_ID, handler.process)

    worker = OutboxWorker(store=outbox_store, processors=processors)
    return publisher, worker, mongo_database


def test_sales_monitoring_audit_handler_persists_finding(mongo_database: Database) -> None:
    publisher, worker, db = _build_audit_pipeline(mongo_database)
    sales_store = MongoMachineSalesStore.from_collection(db["machine_sales"])
    inserted = sales_store.insert_if_absent(
        MachineSale(
            source_id="kv-sm-audit-1",
            machine_id=_MACHINE_ID,
            product_code="coffee-1",
            quantity=Decimal("1"),
            occurred_at=_SALE_AT,
            ingested_at=_OCCURRED,
            sale_kind="coffee",
            price=_SALE_PRICE,
        ),
    )
    assert inserted is True
    persisted = sales_store.find_in_window(
        _MACHINE_ID,
        opened_at=_WINDOW_OPEN,
        closed_at=_OCCURRED,
    )
    assert len(persisted) == 1
    assert persisted[0].price == _SALE_PRICE

    event = SalesMonitoringYesterdayNoSales(
        event_id=EventId(_SALES_AUDIT_ID),
        machine_id=_MACHINE_ID,
        report_day=_REPORT_DAY,
        occurred_at=_OCCURRED,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )

    publisher.publish(event)
    processed = asyncio.run(
        worker.process_batch_for_handler(SALES_MONITORING_AUDIT_HANDLER_ID),
    )

    assert processed == 1
    document = db["sales_monitoring_audit"].find_one({"_id": _SALES_AUDIT_ID})
    assert document is not None
    assert document["_id"] == _SALES_AUDIT_ID
    assert document["event_type"] == "SalesMonitoringYesterdayNoSales"
    assert document["machine_id"] == _MACHINE_ID.value
    assert document["report_day"] == _REPORT_DAY.isoformat()

    outbox_entry = db["domain_event_outbox"].find_one(
        {"handler_id": SALES_MONITORING_AUDIT_HANDLER_ID},
    )
    assert outbox_entry is not None
    assert outbox_entry["status"] == "processed"


def test_sales_monitoring_offline_open_persists_open_status(mongo_database: Database) -> None:
    publisher, worker, db = _build_audit_pipeline(mongo_database)
    event = SalesMonitoringOfflineOpened(
        event_id=EventId(
            f"sales-monitoring-offline-opened:{_MACHINE_ID.value}:{_OPENED_AT.isoformat()}"
        ),
        machine_id=_MACHINE_ID,
        opened_at=_OPENED_AT,
        occurred_at=_OPENED_AT,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )

    publisher.publish(event)
    processed = asyncio.run(
        worker.process_batch_for_handler(SALES_MONITORING_AUDIT_HANDLER_ID),
    )

    assert processed == 1
    document = db["sales_monitoring_audit"].find_one({"_id": _OFFLINE_AUDIT_ID})
    assert document is not None
    assert document["_id"] == _OFFLINE_AUDIT_ID
    assert document["status"] == "open"
    assert document["machine_id"] == _MACHINE_ID.value
