from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pymongo.database import Database

from src.application.outbox.handler_ids import (
    SERVICE_VISIT_INCIDENT_HANDLER_ID,
    SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
)
from src.application.outbox.service_visit_incident import ServiceVisitIncidentHandler
from src.application.outbox.service_visit_on_maintenance import ServiceVisitOnMaintenanceHandler
from src.application.service_visits import (
    NullMachineSalesQtyBaselineLookup,
    NullMaintenanceOnOperationalDayLookup,
)
from src.application.service_visits.clear_no_sales import ClearNoSalesIncident
from src.application.service_visits.clear_offline import ClearOfflineIncident
from src.application.service_visits.close_visit import CloseServiceVisit
from src.application.service_visits.materialize import MachineSchedule, MaterializeScheduledVisits
from src.application.service_visits.models import VisitStatus
from src.application.service_visits.open_incident import OpenServiceIncident
from src.application.service_visits.visit_ids import offline_incident_visit_id, scheduled_visit_id
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations import MaintenanceCompleted
from src.domain.sales_monitoring import SalesMonitoringOfflineOpened
from src.infrastructure.mongodb.service_visits import MongoServiceVisitStore
from src.infrastructure.outbox.mongo import MongoOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.outbox.worker import OutboxWorker

pytestmark = pytest.mark.integration

_MACHINE = MachineId("101")
_TECH = TechnicianId("001")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_WED = date(2026, 8, 12)
_AT = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)
_OPENED = EventId("off-int-1")


def _materialize(visit_store: MongoServiceVisitStore) -> MaterializeScheduledVisits:
    return MaterializeScheduledVisits(
        store=visit_store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=6,
    )


class _Weekdays:
    def weekdays_for(self, machine_id: MachineId) -> frozenset[int]:
        del machine_id
        return frozenset({2})


def _build_visits_pipeline(
    mongo_database: Database,
) -> tuple[OutboxDomainEventPublisher, OutboxWorker, MongoServiceVisitStore, Database]:
    outbox_store = MongoOutboxStore.from_collection(
        mongo_database["domain_event_outbox"],
        max_attempts=3,
    )
    visit_store = MongoServiceVisitStore(mongo_database["service_visits"])
    publisher = OutboxDomainEventPublisher(store=outbox_store)
    publisher.subscribe(MaintenanceCompleted, SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID)
    publisher.subscribe(SalesMonitoringOfflineOpened, SERVICE_VISIT_INCIDENT_HANDLER_ID)

    processors = OutboxProcessorRegistry()
    processors.register(
        SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
        ServiceVisitOnMaintenanceHandler(
            closer=CloseServiceVisit(store=visit_store),
            weekdays=_Weekdays(),
            timezone=_TZ,
            day_end_hour=6,
        ).process,
    )
    processors.register(
        SERVICE_VISIT_INCIDENT_HANDLER_ID,
        ServiceVisitIncidentHandler(
            opener=OpenServiceIncident(
                store=visit_store,
                baseline_lookup=NullMachineSalesQtyBaselineLookup(),
                min_baseline_qty=Decimal("0"),
            ),
            clearer=ClearOfflineIncident(store=visit_store),
            no_sales_clearer=ClearNoSalesIncident(store=visit_store),
            timezone=_TZ,
            day_end_hour=6,
        ).process,
    )
    worker = OutboxWorker(store=outbox_store, processors=processors)
    return publisher, worker, visit_store, mongo_database


def test_maintenance_completed_closes_visit_via_outbox(mongo_database: Database) -> None:
    publisher, worker, visit_store, db = _build_visits_pipeline(mongo_database)
    _materialize(visit_store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_AT,
    )
    visit_id = scheduled_visit_id(_MACHINE, _WED)
    event = MaintenanceCompleted(
        event_id=EventId("mnt-int-1"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=_AT,
        occurred_at=_AT,
    )

    publisher.publish(event)
    processed = asyncio.run(
        worker.process_batch_for_handler(SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID),
    )

    assert processed == 1
    document = db["service_visits"].find_one({"_id": visit_id})
    assert document is not None
    assert document["status"] == VisitStatus.COMPLETED.value
    loaded = visit_store.get(visit_id)
    assert loaded is not None
    assert loaded.status is VisitStatus.COMPLETED


def test_offline_opened_does_not_create_extra_via_outbox(mongo_database: Database) -> None:
    publisher, worker, visit_store, db = _build_visits_pipeline(mongo_database)
    event = SalesMonitoringOfflineOpened(
        event_id=_OPENED,
        machine_id=_MACHINE,
        opened_at=_AT,
        occurred_at=_AT,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    extra_id = offline_incident_visit_id(_OPENED)

    publisher.publish(event)
    processed = asyncio.run(
        worker.process_batch_for_handler(SERVICE_VISIT_INCIDENT_HANDLER_ID),
    )

    assert processed == 1
    assert db["service_visits"].find_one({"_id": extra_id}) is None
    assert visit_store.get(extra_id) is None
