from __future__ import annotations

import asyncio
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from src.application.form_submissions import NonRetryableOutboxError
from src.application.outbox.handler_ids import SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID
from src.application.outbox.service_visit_on_maintenance import (
    ServiceVisitOnMaintenanceHandler,
)
from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.close_visit import CloseServiceVisit
from src.application.service_visits.materialize import MachineSchedule, MaterializeScheduledVisits
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import VisitStatus
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import BatchId, EventId, MachineId, TechnicianId
from src.domain.machine_operations import MaintenanceCompleted, PhotosSubmitted
from src.domain.sales_monitoring import SalesMonitoringYesterdayDecline

_MACHINE = MachineId("101")
_TECH = TechnicianId("001")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_WED = date(2026, 8, 12)
_AT = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)


def _materialize(store: InMemoryServiceVisitStore) -> MaterializeScheduledVisits:
    return MaterializeScheduledVisits(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=6,
    )


class _Weekdays:
    def weekdays_for(self, machine_id: MachineId) -> frozenset[int]:
        del machine_id
        return frozenset({2})


def test_maintenance_handler_closes_closable_scheduled() -> None:
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_AT,
    )
    handler = ServiceVisitOnMaintenanceHandler(
        closer=CloseServiceVisit(store=store),
        weekdays=_Weekdays(),
        timezone=_TZ,
        day_end_hour=6,
    )
    event = MaintenanceCompleted(
        event_id=EventId("mnt-1"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=_AT,
        occurred_at=_AT,
    )
    asyncio.run(handler.process(event))
    visit = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert visit is not None
    assert visit.status is VisitStatus.COMPLETED


def test_maintenance_handler_close_same_event_is_idempotent() -> None:
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_AT,
    )
    handler = ServiceVisitOnMaintenanceHandler(
        closer=CloseServiceVisit(store=store),
        weekdays=_Weekdays(),
        timezone=_TZ,
        day_end_hour=6,
    )
    event = MaintenanceCompleted(
        event_id=EventId("mnt-1"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        completed_at=_AT,
        occurred_at=_AT,
    )
    asyncio.run(handler.process(event))
    asyncio.run(handler.process(event))
    assert SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID == "service_visit_on_maintenance"
    visit = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert visit is not None
    assert visit.status is VisitStatus.COMPLETED


def test_maintenance_handler_rejects_unsupported_event() -> None:
    handler = ServiceVisitOnMaintenanceHandler(
        closer=CloseServiceVisit(store=InMemoryServiceVisitStore()),
        weekdays=_Weekdays(),
        timezone=_TZ,
        day_end_hour=6,
    )
    event = SalesMonitoringYesterdayDecline(
        event_id=EventId("dec-1"),
        machine_id=_MACHINE,
        report_day=_WED,
        occurred_at=_AT,
        report_sum=Decimal("0"),
        baseline_avg=Decimal("1"),
        drop_percent=0,
        assigned_technician_id=None,
        assigned_technician_display=None,
        last_serviced_by_technician_id=None,
        last_serviced_by_display=None,
        last_serviced_at=None,
    )
    with pytest.raises(NonRetryableOutboxError):
        asyncio.run(handler.process(event))


def test_service_visit_handler_closes_for_photo_embedded_maintenance() -> None:
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_AT,
    )
    handler = ServiceVisitOnMaintenanceHandler(
        closer=CloseServiceVisit(store=store),
        weekdays=_Weekdays(),
        timezone=_TZ,
        day_end_hour=6,
    )
    event = PhotosSubmitted(
        event_id=EventId("photo-mnt-1"),
        batch_id=BatchId("batch-1"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=2,
        submitted_at=_AT,
        occurred_at=_AT,
        maintenance_completed_at=_AT,
    )
    asyncio.run(handler.process(event))
    visit = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert visit is not None
    assert visit.status is VisitStatus.COMPLETED


def test_photo_without_embedded_maintenance_does_not_close_visit() -> None:
    store = InMemoryServiceVisitStore()
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_AT,
    )
    handler = ServiceVisitOnMaintenanceHandler(
        closer=CloseServiceVisit(store=store),
        weekdays=_Weekdays(),
        timezone=_TZ,
        day_end_hour=6,
    )
    event = PhotosSubmitted(
        event_id=EventId("photo-no-mnt"),
        batch_id=BatchId("batch-2"),
        technician_id=_TECH,
        machine_id=_MACHINE,
        photo_count=2,
        submitted_at=_AT,
        occurred_at=_AT,
        maintenance_completed_at=None,
    )
    asyncio.run(handler.process(event))
    visit = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert visit is not None
    assert visit.status is VisitStatus.OPEN
