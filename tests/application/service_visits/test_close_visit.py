from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.service_visits import (
    NullMachineSalesQtyBaselineLookup,
    NullMaintenanceOnOperationalDayLookup,
)
from src.application.service_visits.close_visit import CloseServiceVisit
from src.application.service_visits.materialize import MachineSchedule, MaterializeScheduledVisits
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import CloseType, VisitStatus
from src.application.service_visits.visit_ids import ad_hoc_visit_id, scheduled_visit_id
from src.domain.ids import EventId, MachineId, TechnicianId

_MACHINE = MachineId("101")
_TECH = TechnicianId("001")
_TZ = ZoneInfo("Asia/Yekaterinburg")
_TUE = date(2026, 8, 11)
_WED = date(2026, 8, 12)
_NOW = datetime(2026, 8, 12, 10, 0, tzinfo=_TZ)
_EVENT = EventId("mnt-wed")
_END_HOUR = 6


def _materialize(store: InMemoryServiceVisitStore) -> MaterializeScheduledVisits:
    return MaterializeScheduledVisits(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )


def _stack() -> InMemoryServiceVisitStore:
    store = InMemoryServiceVisitStore()
    use_case = _materialize(store)
    catalog = (MachineSchedule(_MACHINE, frozenset({1, 2})),)
    use_case.execute(due_date=_TUE, catalog=catalog, now=_NOW)
    use_case.execute(due_date=_WED, catalog=catalog, now=_NOW)
    return store


def test_close_wednesday_marks_tuesday_missed() -> None:
    store = _stack()
    CloseServiceVisit(store=store).execute(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=_EVENT,
        completed_at=_NOW,
        service_weekdays=frozenset({1, 2}),
        timezone=_TZ,
        day_end_hour=6,
        now=_NOW,
    )
    tuesday = store.get(scheduled_visit_id(_MACHINE, _TUE))
    wednesday = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert wednesday is not None and wednesday.status is VisitStatus.COMPLETED
    assert wednesday.close_type is CloseType.SCHEDULED
    assert tuesday is not None and tuesday.status is VisitStatus.MISSED


def test_close_buried_tuesday_is_noop_not_completed() -> None:
    store = _stack()
    closer = CloseServiceVisit(store=store)
    closer.execute(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=_EVENT,
        completed_at=_NOW,
        service_weekdays=frozenset({1, 2}),
        timezone=_TZ,
        day_end_hour=6,
        now=_NOW,
    )
    closer.execute(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=EventId("mnt-2"),
        completed_at=datetime(2026, 8, 12, 11, 0, tzinfo=_TZ),
        service_weekdays=frozenset({1, 2}),
        timezone=_TZ,
        day_end_hour=6,
        now=_NOW,
    )
    tuesday = store.get(scheduled_visit_id(_MACHINE, _TUE))
    assert tuesday is not None
    assert tuesday.status is VisitStatus.MISSED
    assert tuesday.close_type is None


def test_adhoc_close_unscheduled_roster_when_weekdays_empty() -> None:
    store = InMemoryServiceVisitStore()
    CloseServiceVisit(store=store).execute(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=_EVENT,
        completed_at=_NOW,
        service_weekdays=frozenset(),
        timezone=_TZ,
        day_end_hour=6,
        now=_NOW,
    )
    visit = store.get(ad_hoc_visit_id(_MACHINE, _WED, _EVENT))
    assert visit is not None
    assert visit.close_type is CloseType.UNSCHEDULED_ROSTER
    assert visit.status is VisitStatus.COMPLETED


def test_adhoc_close_spontaneous_when_weekdays_present() -> None:
    store = InMemoryServiceVisitStore()
    CloseServiceVisit(store=store).execute(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=_EVENT,
        completed_at=_NOW,
        service_weekdays=frozenset({0}),
        timezone=_TZ,
        day_end_hour=6,
        now=_NOW,
    )
    visit = store.get(ad_hoc_visit_id(_MACHINE, _WED, _EVENT))
    assert visit is not None
    assert visit.close_type is CloseType.SPONTANEOUS


def test_close_extra_marks_buried_scheduled_missed() -> None:
    store = InMemoryServiceVisitStore()
    from src.application.service_visits.models import IncidentSource
    from src.application.service_visits.open_incident import OpenServiceIncident
    from src.application.service_visits.visit_ids import offline_incident_visit_id

    catalog = (MachineSchedule(_MACHINE, frozenset({1})),)
    _materialize(store).execute(
        due_date=_TUE,
        catalog=catalog,
        now=_NOW,
    )
    opened = EventId("off-1")
    OpenServiceIncident(
        store=store,
        baseline_lookup=NullMachineSalesQtyBaselineLookup(),
        min_baseline_qty=Decimal("0"),
    ).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(opened),
        now=_NOW,
    )
    CloseServiceVisit(store=store).execute(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=_EVENT,
        completed_at=_NOW,
        service_weekdays=frozenset({1}),
        timezone=_TZ,
        day_end_hour=6,
        now=_NOW,
    )
    extra = store.get(offline_incident_visit_id(opened))
    tuesday = store.get(scheduled_visit_id(_MACHINE, _TUE))
    assert extra is not None
    assert extra.status is VisitStatus.COMPLETED
    assert extra.close_type is CloseType.EXTRA_INCIDENT
    assert tuesday is not None
    assert tuesday.status is VisitStatus.MISSED


def test_close_same_maintenance_event_is_noop() -> None:
    store = InMemoryServiceVisitStore()
    closer = CloseServiceVisit(store=store)
    payload = dict(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=_EVENT,
        completed_at=_NOW,
        service_weekdays=frozenset(),
        timezone=_TZ,
        day_end_hour=6,
        now=_NOW,
    )
    closer.execute(**payload)
    closer.execute(**payload)
    visits = store.list_for_machine(_MACHINE, status=VisitStatus.COMPLETED)
    assert len(visits) == 1
    assert visits[0].visit_id == ad_hoc_visit_id(_MACHINE, _WED, _EVENT)


def test_early_adhoc_clears_buried_scheduled_overdue() -> None:
    # edge ISS-368: ранний/спонтанный визит хоронит leftover (не closable), без ложного overdue
    from src.application.service_visits.models import ServiceVisit, VisitKind

    store = InMemoryServiceVisitStore()
    leftover_id = scheduled_visit_id(_MACHINE, _TUE)
    store.upsert(
        ServiceVisit(
            visit_id=leftover_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_TUE,
            status=VisitStatus.OPEN,
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
    CloseServiceVisit(store=store).execute(
        machine_id=_MACHINE,
        technician_id=_TECH,
        maintenance_event_id=_EVENT,
        completed_at=_NOW,
        service_weekdays=frozenset({1, 2}),
        timezone=_TZ,
        day_end_hour=6,
        now=_NOW,
    )
    leftover = store.get(leftover_id)
    ad_hoc = store.get(ad_hoc_visit_id(_MACHINE, _WED, _EVENT))
    assert ad_hoc is not None and ad_hoc.status is VisitStatus.COMPLETED
    assert leftover is not None and leftover.status is VisitStatus.MISSED
