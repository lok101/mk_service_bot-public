from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from beartype import beartype
from pymongo.database import Database

from src.application.service_visits import (
    CloseServiceVisit,
    CloseType,
    RefreshScheduledVisitsForRosterChange,
    RosterWeekdayChange,
    VisitStatus,
    ad_hoc_visit_id,
    scheduled_visit_id,
)
from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.machine_operations import MaintenanceCompleted
from src.infrastructure.composition.factories import build_maintenance_on_operational_day_lookup
from src.infrastructure.mongodb import MongoEventStore
from src.infrastructure.mongodb.service_visits import MongoServiceVisitStore

pytestmark = pytest.mark.integration

_MACHINE = MachineId("101")
_TECH = TechnicianId("001")
_EVENT = EventId("mnt-retro-int-1")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_OPS_DAY = date(2026, 8, 12)
_END_HOUR = 6
_COMPLETED_AT = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)
_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=_TZ)


@beartype
def _build_refresh(
    mongo_database: Database,
) -> tuple[MongoServiceVisitStore, RefreshScheduledVisitsForRosterChange]:
    event_store = MongoEventStore.from_collection(mongo_database["machine_events"])
    visit_store = MongoServiceVisitStore(mongo_database["service_visits"])
    event_store.append(
        MaintenanceCompleted(
            event_id=_EVENT,
            technician_id=_TECH,
            machine_id=_MACHINE,
            completed_at=_COMPLETED_AT,
            occurred_at=_COMPLETED_AT,
        ),
        expected_version=0,
    )
    CloseServiceVisit(store=visit_store).execute(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=_EVENT,
        completed_at=_COMPLETED_AT,
        service_weekdays=frozenset(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
        now=_NOW,
    )
    refresh = RefreshScheduledVisitsForRosterChange(
        store=visit_store,
        maintenance_lookup=build_maintenance_on_operational_day_lookup(event_store),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    return visit_store, refresh


def test_maintenance_then_roster_add_day_completes_scheduled(mongo_database: Database) -> None:
    visit_store, refresh = _build_refresh(mongo_database)
    ad_hoc_id = ad_hoc_visit_id(_MACHINE, _OPS_DAY, _EVENT)

    ad_hoc_visit = visit_store.get(ad_hoc_id)
    assert ad_hoc_visit is not None
    assert ad_hoc_visit.close_type is CloseType.UNSCHEDULED_ROSTER
    assert ad_hoc_visit.status is VisitStatus.COMPLETED

    result = refresh.execute(
        changes=(RosterWeekdayChange(_MACHINE, frozenset({_OPS_DAY.weekday()})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )

    scheduled = visit_store.get(scheduled_visit_id(_MACHINE, _OPS_DAY))
    assert scheduled is not None
    assert scheduled.status is VisitStatus.COMPLETED
    assert scheduled.close_type is CloseType.SCHEDULED
    assert scheduled.maintenance_event_id == _EVENT
    assert visit_store.get(ad_hoc_id) is None
    assert result.upserted == 0
    assert result.retrospectively_closed == 1
