from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from tests.application.service_visits.maintenance_lookup_fakes import (
    FakeMaintenanceOnOperationalDayLookup,
)

from src.application.service_visits import (
    NullMachineSalesQtyBaselineLookup,
    NullMaintenanceOnOperationalDayLookup,
    RefreshScheduledVisitsForRosterChange,
    RosterWeekdayChange,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import IncidentSource, ServiceVisit
from src.application.service_visits.open_incident import OpenServiceIncident
from src.application.service_visits.ports import MaintenanceOnOperationalDaySnapshot
from src.application.service_visits.visit_ids import offline_incident_visit_id, scheduled_visit_id
from src.domain.ids import EventId, MachineId, TechnicianId

_MACHINE = MachineId("101")
_TZ = ZoneInfo("Europe/Moscow")
_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=_TZ)
_WED = date(2026, 8, 12)
_END_HOUR = 6
_OPENED = EventId("off-roster-1")


def test_refresh_adds_today_open_scheduled() -> None:
    store = InMemoryServiceVisitStore()
    result = RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    ).execute(
        changes=(RosterWeekdayChange(_MACHINE, frozenset({2})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None
    assert slot.kind is VisitKind.SCHEDULED
    assert slot.status is VisitStatus.OPEN
    assert result.upserted == 1


def test_refresh_adds_today_completed_when_maintenance_exists() -> None:
    store = InMemoryServiceVisitStore()
    lookup = FakeMaintenanceOnOperationalDayLookup(
        {
            (_MACHINE, _WED): MaintenanceOnOperationalDaySnapshot(
                event_id=EventId("mnt-wed"),
                technician_id=TechnicianId("001"),
                completed_at=datetime(2026, 8, 12, 9, 0, tzinfo=ZoneInfo("UTC")),
            )
        },
    )
    refresh = RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=lookup,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    result = refresh.execute(
        changes=(RosterWeekdayChange(_MACHINE, frozenset({2})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    slot = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert slot is not None and slot.status is VisitStatus.COMPLETED
    assert result.upserted == 0
    assert result.retrospectively_closed == 1


def test_refresh_removes_open_scheduled_when_day_dropped() -> None:
    store = InMemoryServiceVisitStore()
    refresh = RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    refresh.execute(
        changes=(RosterWeekdayChange(_MACHINE, frozenset({2})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    result = refresh.execute(
        changes=(RosterWeekdayChange(_MACHINE, frozenset({0})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is None
    assert result.cancelled == 1


def test_refresh_keeps_extra_incident() -> None:
    store = InMemoryServiceVisitStore()
    OpenServiceIncident(
        store=store,
        baseline_lookup=NullMachineSalesQtyBaselineLookup(),
        min_baseline_qty=Decimal("0"),
    ).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    ).execute(
        changes=(RosterWeekdayChange(_MACHINE, frozenset({0})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    extra = store.get(offline_incident_visit_id(_OPENED))
    assert extra is not None
    assert extra.kind is VisitKind.EXTRA_INCIDENT
    assert extra.status is VisitStatus.OPEN


def test_refresh_does_not_touch_completed_scheduled() -> None:
    store = InMemoryServiceVisitStore()
    visit_id = scheduled_visit_id(_MACHINE, _WED)
    store.upsert(
        ServiceVisit(
            visit_id=visit_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_WED,
            status=VisitStatus.COMPLETED,
            closable=False,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=_NOW,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    ).execute(
        changes=(RosterWeekdayChange(_MACHINE, frozenset({0})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    loaded = store.get(visit_id)
    assert loaded is not None
    assert loaded.status is VisitStatus.COMPLETED


def test_refresh_skips_machines_not_in_weekday_change_set() -> None:
    store = InMemoryServiceVisitStore()
    OpenServiceIncident(
        store=store,
        baseline_lookup=NullMachineSalesQtyBaselineLookup(),
        min_baseline_qty=Decimal("0"),
    ).execute(
        machine_id=_MACHINE,
        ops_day=_WED,
        source=IncidentSource.OFFLINE,
        visit_id=offline_incident_visit_id(_OPENED),
        now=_NOW,
    )
    RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    ).execute(
        changes=(),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    extra = store.get(offline_incident_visit_id(_OPENED))
    assert extra is not None
    assert extra.status is VisitStatus.OPEN


def test_refresh_cancels_open_scheduled_on_unassign() -> None:
    # happy: technician снят → open scheduled сегодня удаляется
    store = InMemoryServiceVisitStore()
    refresh = RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    refresh.execute(
        changes=(RosterWeekdayChange(_MACHINE, frozenset({2})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is not None
    result = refresh.execute(
        changes=(),
        unassigned_machine_ids=(_MACHINE,),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert store.get(scheduled_visit_id(_MACHINE, _WED)) is None
    assert result.cancelled == 1


def test_refresh_keeps_completed_scheduled_on_unassign() -> None:
    # edge: completed сегодня при unassign остаётся
    store = InMemoryServiceVisitStore()
    visit_id = scheduled_visit_id(_MACHINE, _WED)
    store.upsert(
        ServiceVisit(
            visit_id=visit_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=_WED,
            status=VisitStatus.COMPLETED,
            closable=False,
            priority_boost=False,
            incident_source=None,
            close_type=None,
            completed_at=_NOW,
            completed_by_technician_id=TechnicianId("001"),
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    result = RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    ).execute(
        changes=(),
        unassigned_machine_ids=(_MACHINE,),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    loaded = store.get(visit_id)
    assert loaded is not None
    assert loaded.status is VisitStatus.COMPLETED
    assert result.cancelled == 0


def test_refresh_cancels_leftover_when_weekday_removed() -> None:
    # happy ISS-368: снятие дня из графика → open leftover того weekday удаляется
    store = InMemoryServiceVisitStore()
    monday = date(2026, 8, 10)  # weekday 0
    leftover_id = scheduled_visit_id(_MACHINE, monday)
    store.upsert(
        ServiceVisit(
            visit_id=leftover_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=monday,
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
    result = RefreshScheduledVisitsForRosterChange(
        store=store,
        maintenance_lookup=NullMaintenanceOnOperationalDayLookup(),
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    ).execute(
        # среда (2) остаётся; понедельник (0) снят
        changes=(RosterWeekdayChange(_MACHINE, frozenset({2})),),
        now=_NOW,
        timezone=_TZ,
        day_end_hour=_END_HOUR,
    )
    assert store.get(leftover_id) is None
    assert result.cancelled >= 1
    today = store.get(scheduled_visit_id(_MACHINE, _WED))
    assert today is not None
    assert today.status is VisitStatus.OPEN
