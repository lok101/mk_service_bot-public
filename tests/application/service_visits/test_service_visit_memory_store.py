from __future__ import annotations

from datetime import UTC, date, datetime

from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.models import (
    CloseType,
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.visit_ids import (
    offline_incident_visit_id,
    scheduled_visit_id,
)
from src.domain.ids import EventId, MachineId, TechnicianId

_NOW = datetime(2026, 8, 11, 6, 0, tzinfo=UTC)
_MACHINE = MachineId("101")
_TECHNICIAN = TechnicianId("001")


def _scheduled(due: date, *, closable: bool = True) -> ServiceVisit:
    visit_id = scheduled_visit_id(_MACHINE, due)
    return ServiceVisit(
        visit_id=visit_id,
        machine_id=_MACHINE,
        kind=VisitKind.SCHEDULED,
        due_date=due,
        status=VisitStatus.OPEN,
        closable=closable,
        priority_boost=False,
        incident_source=None,
        close_type=None,
        completed_at=None,
        completed_by_technician_id=None,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _extra(
    *,
    event_suffix: str,
    source: IncidentSource,
    status: VisitStatus = VisitStatus.OPEN,
) -> ServiceVisit:
    visit_id = offline_incident_visit_id(EventId(f"off-{event_suffix}"))
    return ServiceVisit(
        visit_id=visit_id,
        machine_id=_MACHINE,
        kind=VisitKind.EXTRA_INCIDENT,
        due_date=date(2026, 8, 12),
        status=status,
        closable=True,
        priority_boost=False,
        incident_source=source,
        close_type=None,
        completed_at=None,
        completed_by_technician_id=None,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_list_open_extras_filters_by_incident_source() -> None:
    store = InMemoryServiceVisitStore()
    offline_open = _extra(event_suffix="1", source=IncidentSource.OFFLINE)
    no_sales_open = _extra(event_suffix="2", source=IncidentSource.NO_SALES)
    offline_cleared = _extra(
        event_suffix="3",
        source=IncidentSource.OFFLINE,
        status=VisitStatus.CLEARED,
    )
    store.upsert(offline_open)
    store.upsert(no_sales_open)
    store.upsert(offline_cleared)
    store.upsert(_scheduled(date(2026, 8, 12)))

    offline_only = store.list_open_extras(incident_source=IncidentSource.OFFLINE)
    assert [v.visit_id for v in offline_only] == [offline_open.visit_id]

    all_open = store.list_open_extras()
    assert {v.visit_id for v in all_open} == {
        offline_open.visit_id,
        no_sales_open.visit_id,
    }


def test_memory_upsert_same_id_replaces_document() -> None:
    store = InMemoryServiceVisitStore()
    first = _scheduled(date(2026, 8, 11), closable=True)
    store.upsert(first)
    updated = _scheduled(date(2026, 8, 11), closable=False)
    store.upsert(updated)
    loaded = store.get(first.visit_id)
    assert loaded is not None
    assert loaded.closable is False


def test_list_for_machine_filters_by_status() -> None:
    store = InMemoryServiceVisitStore()
    open_visit = _scheduled(date(2026, 8, 11))
    store.upsert(open_visit)
    listed = store.list_for_machine(_MACHINE, status=VisitStatus.OPEN)
    assert [item.visit_id for item in listed] == [open_visit.visit_id]
    assert store.list_for_machine(_MACHINE, status=VisitStatus.COMPLETED) == []


def test_memory_delete_removes_visit() -> None:
    store = InMemoryServiceVisitStore()
    visit = _scheduled(date(2026, 8, 11))
    store.upsert(visit)
    store.delete(visit.visit_id)
    assert store.get(visit.visit_id) is None


def test_memory_delete_missing_is_noop() -> None:
    store = InMemoryServiceVisitStore()
    store.delete("scheduled:101:2026-08-11")
    assert store.get("scheduled:101:2026-08-11") is None


def _completed(due: date, *, at: datetime) -> ServiceVisit:
    return ServiceVisit(
        visit_id=f"done:{_MACHINE.value}:{due.isoformat()}",
        machine_id=_MACHINE,
        kind=VisitKind.SCHEDULED,
        due_date=due,
        status=VisitStatus.COMPLETED,
        closable=False,
        priority_boost=False,
        incident_source=None,
        close_type=CloseType.SCHEDULED,
        completed_at=at,
        completed_by_technician_id=_TECHNICIAN,
        maintenance_event_id=None,
        created_at=_NOW,
        updated_at=at,
    )


def test_list_for_due_date_range_inclusive() -> None:
    store = InMemoryServiceVisitStore()
    before = _scheduled(date(2026, 7, 31))
    first = _scheduled(date(2026, 8, 1))
    last = _scheduled(date(2026, 8, 31))
    after = _scheduled(date(2026, 9, 1))
    for visit in (before, first, last, after):
        store.upsert(visit)

    listed = store.list_for_due_date_range(start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert [visit.visit_id for visit in listed] == [first.visit_id, last.visit_id]


def test_list_for_due_date_range_includes_completed_and_open_scheduled() -> None:
    store = InMemoryServiceVisitStore()
    open_scheduled = _scheduled(date(2026, 8, 4))
    completed = _completed(date(2026, 8, 11), at=datetime(2026, 8, 11, 9, 0, tzinfo=UTC))
    store.upsert(open_scheduled)
    store.upsert(completed)

    listed = store.list_for_due_date_range(start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert {visit.visit_id for visit in listed} == {
        open_scheduled.visit_id,
        completed.visit_id,
    }
    assert {visit.status for visit in listed} == {VisitStatus.OPEN, VisitStatus.COMPLETED}
