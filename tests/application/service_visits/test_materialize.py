from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from tests.application.service_visits.maintenance_lookup_fakes import (
    FakeMaintenanceOnOperationalDayLookup,
)

from src.application.service_visits import NullMaintenanceOnOperationalDayLookup
from src.application.service_visits.materialize import MachineSchedule, MaterializeScheduledVisits
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import CloseType, VisitKind, VisitStatus
from src.application.service_visits.ports import MaintenanceOnOperationalDaySnapshot
from src.application.service_visits.visit_ids import scheduled_visit_id
from src.domain.ids import EventId, MachineId, TechnicianId

_MACHINE = MachineId("101")
_TUE = date(2026, 8, 11)
_WED = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 6, 0, tzinfo=UTC)
_TZ = ZoneInfo("Asia/Yekaterinburg")
_END_HOUR = 6


def _materialize(
    store: InMemoryServiceVisitStore,
    *,
    lookup: FakeMaintenanceOnOperationalDayLookup
    | NullMaintenanceOnOperationalDayLookup
    | None = None,
) -> MaterializeScheduledVisits:
    return MaterializeScheduledVisits(
        store=store,
        maintenance_lookup=lookup or NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )


def test_materialize_wednesday_buries_tuesday_not_closable() -> None:
    store = InMemoryServiceVisitStore()
    use_case = _materialize(store)
    catalog = (MachineSchedule(_MACHINE, frozenset({1, 2})),)
    use_case.execute(due_date=_TUE, catalog=catalog, now=_NOW)
    use_case.execute(due_date=_WED, catalog=catalog, now=_NOW)
    tuesday = store.get(scheduled_visit_id(_MACHINE, _TUE))
    wednesday = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert tuesday is not None and wednesday is not None
    assert tuesday.status is VisitStatus.OPEN
    assert tuesday.closable is False
    assert wednesday.closable is True
    assert wednesday.kind is VisitKind.SCHEDULED


def test_materialize_retrospective_close_creates_completed_scheduled() -> None:
    store = InMemoryServiceVisitStore()
    tech = TechnicianId("001")
    event = EventId("mnt-wed")
    completed_at = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    lookup = FakeMaintenanceOnOperationalDayLookup(
        {
            (_MACHINE, _WED): MaintenanceOnOperationalDaySnapshot(
                event_id=event,
                technician_id=tech,
                completed_at=completed_at,
            )
        },
    )
    result = _materialize(store, lookup=lookup).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None
    assert slot.status is VisitStatus.COMPLETED
    assert slot.close_type is CloseType.SCHEDULED
    assert slot.closable is False
    assert slot.priority_boost is False
    assert slot.maintenance_event_id == event
    assert slot.completed_by_technician_id == tech
    assert slot.completed_at == completed_at
    assert result.retrospectively_closed == 1
    assert result.upserted == 0


def test_materialize_retrospective_close_deletes_matching_ad_hoc() -> None:
    from src.application.service_visits.models import ServiceVisit
    from src.application.service_visits.visit_ids import ad_hoc_visit_id

    store = InMemoryServiceVisitStore()
    tech = TechnicianId("001")
    event = EventId("mnt-wed")
    completed_at = datetime(2026, 8, 12, 10, 0, tzinfo=UTC)
    ad_hoc_id = ad_hoc_visit_id(_MACHINE, _WED, event)
    store.upsert(
        ServiceVisit(
            visit_id=ad_hoc_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_WED,
            status=VisitStatus.COMPLETED,
            closable=False,
            priority_boost=False,
            incident_source=None,
            close_type=CloseType.SPONTANEOUS,
            completed_at=completed_at,
            completed_by_technician_id=tech,
            maintenance_event_id=event,
            created_at=completed_at,
            updated_at=completed_at,
        ),
    )
    lookup = FakeMaintenanceOnOperationalDayLookup(
        {
            (_MACHINE, _WED): MaintenanceOnOperationalDaySnapshot(
                event_id=event,
                technician_id=tech,
                completed_at=completed_at,
            )
        },
    )
    _materialize(store, lookup=lookup).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    assert store.get(ad_hoc_id) is None
    scheduled = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert scheduled is not None
    assert scheduled.close_type is CloseType.SCHEDULED


def test_materialize_retrospective_close_repairs_open_scheduled() -> None:
    from src.application.service_visits.models import ServiceVisit

    store = InMemoryServiceVisitStore()
    visit_id = scheduled_visit_id(_MACHINE, _WED)
    store.upsert(
        ServiceVisit(
            visit_id=visit_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_WED,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    event = EventId("mnt-wed")
    lookup = FakeMaintenanceOnOperationalDayLookup(
        {
            (_MACHINE, _WED): MaintenanceOnOperationalDaySnapshot(
                event_id=event,
                technician_id=TechnicianId("001"),
                completed_at=datetime(2026, 8, 12, 10, 0, tzinfo=UTC),
            )
        },
    )
    result = _materialize(store, lookup=lookup).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    slot = store.get(visit_id)
    assert slot is not None and slot.status is VisitStatus.COMPLETED
    assert result.retrospectively_closed == 1


def test_materialize_retrospective_close_no_match_keeps_open_scheduled() -> None:
    store = InMemoryServiceVisitStore()
    lookup = FakeMaintenanceOnOperationalDayLookup({})
    _materialize(store, lookup=lookup).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None and slot.status is VisitStatus.OPEN
    assert slot.closable is True


def test_materialize_retrospective_close_uses_earliest_maintenance() -> None:
    store = InMemoryServiceVisitStore()
    completed_at = datetime(2026, 8, 12, 8, 0, tzinfo=UTC)
    lookup = FakeMaintenanceOnOperationalDayLookup(
        {
            (_MACHINE, _WED): MaintenanceOnOperationalDaySnapshot(
                event_id=EventId("mnt-earliest"),
                technician_id=TechnicianId("001"),
                completed_at=completed_at,
            )
        },
    )
    _materialize(store, lookup=lookup).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None
    assert slot.completed_at == completed_at
    assert slot.maintenance_event_id == EventId("mnt-earliest")


def test_materialize_retrospective_close_skips_non_open_scheduled() -> None:
    from src.application.service_visits.models import ServiceVisit

    store = InMemoryServiceVisitStore()
    visit_id = scheduled_visit_id(_MACHINE, _WED)
    store.upsert(
        ServiceVisit(
            visit_id=visit_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_WED,
            status=VisitStatus.MISSED,
            closable=False,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    lookup = FakeMaintenanceOnOperationalDayLookup(
        {
            (_MACHINE, _WED): MaintenanceOnOperationalDaySnapshot(
                event_id=EventId("mnt-wed"),
                technician_id=TechnicianId("001"),
                completed_at=_NOW,
            )
        },
    )
    result = _materialize(store, lookup=lookup).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=_NOW,
    )
    slot = store.get(visit_id)
    assert slot is not None and slot.status is VisitStatus.MISSED
    assert result.retrospectively_closed == 0


def test_materialize_skips_empty_weekdays() -> None:
    store = InMemoryServiceVisitStore()
    use_case = _materialize(store)
    use_case.execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset()),),
        now=_NOW,
    )
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is None


def test_materialize_absorbs_offline_extra_without_boost() -> None:
    store = InMemoryServiceVisitStore()
    from src.application.service_visits.models import IncidentSource, ServiceVisit
    from src.application.service_visits.visit_ids import offline_incident_visit_id

    now = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
    extra_id = offline_incident_visit_id(EventId("off-1"))
    store.upsert(
        ServiceVisit(
            visit_id=extra_id,
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=_TUE,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=IncidentSource.OFFLINE,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=now,
    )
    extra = store.get(extra_id)
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert extra is not None and extra.status is VisitStatus.CLEARED
    assert slot is not None and slot.priority_boost is False


def test_materialize_absorbs_no_sales_extra_into_today_slot() -> None:
    store = InMemoryServiceVisitStore()
    from src.application.service_visits.models import IncidentSource, ServiceVisit
    from src.application.service_visits.visit_ids import no_sales_incident_visit_id

    now = datetime(2026, 8, 12, 3, 0, tzinfo=UTC)
    extra_id = no_sales_incident_visit_id(_MACHINE)
    store.upsert(
        ServiceVisit(
            visit_id=extra_id,
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=_TUE,
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=IncidentSource.NO_SALES,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=now,
            updated_at=now,
        ),
    )
    _materialize(store).execute(
        due_date=_WED,
        catalog=(MachineSchedule(_MACHINE, frozenset({2})),),
        now=now,
    )
    extra = store.get(extra_id)
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert extra is not None and extra.status is VisitStatus.CLEARED
    assert slot is not None and slot.priority_boost is True


def test_tuesday_stays_closable_when_wednesday_not_in_schedule() -> None:
    store = InMemoryServiceVisitStore()
    use_case = _materialize(store)
    catalog = (MachineSchedule(_MACHINE, frozenset({1})),)
    use_case.execute(due_date=_TUE, catalog=catalog, now=_NOW)
    use_case.execute(due_date=_WED, catalog=catalog, now=_NOW)
    tuesday = store.get(scheduled_visit_id(_MACHINE, _TUE))
    assert tuesday is not None
    assert tuesday.closable is True
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is None


def test_materialize_same_day_does_not_reopen_completed_slot() -> None:
    store = InMemoryServiceVisitStore()
    catalog = (MachineSchedule(_MACHINE, frozenset({2})),)
    _materialize(store).execute(due_date=_WED, catalog=catalog, now=_NOW)
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None
    store.upsert(replace(slot, status=VisitStatus.COMPLETED, closable=False))
    _materialize(store).execute(due_date=_WED, catalog=catalog, now=_NOW)
    again = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert again is not None
    assert again.status is VisitStatus.COMPLETED
    assert again.closable is False
