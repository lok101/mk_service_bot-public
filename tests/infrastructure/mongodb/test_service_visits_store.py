from __future__ import annotations

from datetime import UTC, date, datetime

import mongomock

from src.application.service_visits.models import (
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
)
from src.application.service_visits.visit_ids import (
    offline_incident_visit_id,
    scheduled_visit_id,
)
from src.domain.ids import EventId, MachineId
from src.infrastructure.mongodb.service_visits import MongoServiceVisitStore

_MACHINE = MachineId("101")
_NOW = datetime(2026, 8, 12, tzinfo=UTC)


def test_mongo_visit_upsert_same_id_one_document() -> None:
    collection = mongomock.MongoClient().db.service_visits
    store = MongoServiceVisitStore(collection)
    visit_id = scheduled_visit_id(_MACHINE, date(2026, 8, 12))
    visit = ServiceVisit(
        visit_id=visit_id,
        machine_id=_MACHINE,
        kind=VisitKind.SCHEDULED,
        due_date=date(2026, 8, 12),
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
    )
    store.upsert(visit)
    store.upsert(
        ServiceVisit(
            visit_id=visit_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=date(2026, 8, 12),
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
    assert collection.count_documents({}) == 1
    loaded = store.get(visit_id)
    assert loaded is not None
    assert loaded.closable is False


def test_mongo_visit_delete() -> None:
    collection = mongomock.MongoClient().db.service_visits
    store = MongoServiceVisitStore(collection)
    visit_id = scheduled_visit_id(_MACHINE, date(2026, 8, 12))
    store.upsert(
        ServiceVisit(
            visit_id=visit_id,
            machine_id=_MACHINE,
            kind=VisitKind.SCHEDULED,
            due_date=date(2026, 8, 12),
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
    store.delete(visit_id)
    assert store.get(visit_id) is None


def test_mongo_list_open_extras_by_incident_source() -> None:
    collection = mongomock.MongoClient().db.service_visits
    store = MongoServiceVisitStore(collection)
    offline_id = offline_incident_visit_id(EventId("off-m1"))
    other_id = offline_incident_visit_id(EventId("off-m2"))
    store.upsert(
        ServiceVisit(
            visit_id=offline_id,
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=date(2026, 8, 12),
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=IncidentSource.OFFLINE,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    store.upsert(
        ServiceVisit(
            visit_id=other_id,
            machine_id=_MACHINE,
            kind=VisitKind.EXTRA_INCIDENT,
            due_date=date(2026, 8, 12),
            status=VisitStatus.OPEN,
            closable=True,
            priority_boost=False,
            incident_source=IncidentSource.NO_SALES,
            close_type=None,
            completed_at=None,
            completed_by_technician_id=None,
            maintenance_event_id=None,
            created_at=_NOW,
            updated_at=_NOW,
        ),
    )
    listed = store.list_open_extras(incident_source=IncidentSource.OFFLINE)
    assert [v.visit_id for v in listed] == [offline_id]


def _visit(due: date) -> ServiceVisit:
    return ServiceVisit(
        visit_id=scheduled_visit_id(_MACHINE, due),
        machine_id=_MACHINE,
        kind=VisitKind.SCHEDULED,
        due_date=due,
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
    )


def test_mongo_list_for_due_date_range() -> None:
    collection = mongomock.MongoClient().db.service_visits
    store = MongoServiceVisitStore(collection)
    store.ensure_indexes()
    inside_first = _visit(date(2026, 8, 1))
    inside_last = _visit(date(2026, 8, 31))
    store.upsert(_visit(date(2026, 7, 31)))
    store.upsert(inside_first)
    store.upsert(inside_last)
    store.upsert(_visit(date(2026, 9, 1)))

    listed = store.list_for_due_date_range(start=date(2026, 8, 1), end=date(2026, 8, 31))

    assert [visit.visit_id for visit in listed] == [
        inside_first.visit_id,
        inside_last.visit_id,
    ]
    assert "service_visits_due_date" in set(collection.index_information())
