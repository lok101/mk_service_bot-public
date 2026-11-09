from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient

from src.application.service_visits import (
    CloseType,
    IncidentSource,
    ServiceVisit,
    VisitKind,
    VisitStatus,
    VisitTaskSource,
)
from src.config.mongodb import MongoSettings
from src.config.service_visits import ServiceVisitsSettings
from src.domain.ids import EventId, MachineId, TechnicianId
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class ServiceVisitCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


@beartype
def _date_from_document(value: object) -> date:
    if isinstance(value, datetime):
        return _as_utc(value).date()
    if isinstance(value, date):
        return value
    raise ValueError("date field must be datetime or date")


@beartype
def _optional_incident_source(value: object) -> IncidentSource | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("incident_source must be str or None")
    return IncidentSource(value)


@beartype
def _optional_close_type(value: object) -> CloseType | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("close_type must be str or None")
    return CloseType(value)


@beartype
def service_visit_to_document(visit: ServiceVisit) -> dict[str, Any]:
    return {
        "_id": visit.visit_id,
        "visit_id": visit.visit_id,
        "machine_id": visit.machine_id.value,
        "kind": visit.kind.value,
        "due_date": _date_to_utc_midnight(visit.due_date),
        "status": visit.status.value,
        "closable": visit.closable,
        "priority_boost": visit.priority_boost,
        "incident_source": None if visit.incident_source is None else visit.incident_source.value,
        "close_type": None if visit.close_type is None else visit.close_type.value,
        "completed_at": None if visit.completed_at is None else _as_utc(visit.completed_at),
        "completed_by_technician_id": (
            None
            if visit.completed_by_technician_id is None
            else visit.completed_by_technician_id.value
        ),
        "maintenance_event_id": (
            None if visit.maintenance_event_id is None else visit.maintenance_event_id.value
        ),
        "created_at": _as_utc(visit.created_at),
        "updated_at": _as_utc(visit.updated_at),
        "sources": sorted(source.value for source in visit.sources),
        "loading_order_id": visit.loading_order_id,
    }


@beartype
def service_visit_from_document(document: dict[str, Any]) -> ServiceVisit:
    visit_id = document.get("visit_id", document.get("_id"))
    machine_id = document.get("machine_id")
    kind = document.get("kind")
    due_date = document.get("due_date")
    status = document.get("status")
    closable = document.get("closable")
    priority_boost = document.get("priority_boost")
    created_at = document.get("created_at")
    updated_at = document.get("updated_at")
    completed_at = document.get("completed_at")
    technician_raw = document.get("completed_by_technician_id")
    event_raw = document.get("maintenance_event_id")
    if (
        not isinstance(visit_id, str)
        or not isinstance(machine_id, str)
        or not isinstance(kind, str)
        or not isinstance(due_date, datetime | date)
        or not isinstance(status, str)
        or not isinstance(closable, bool)
        or not isinstance(priority_boost, bool)
        or not isinstance(created_at, datetime)
        or not isinstance(updated_at, datetime)
    ):
        raise ValueError("ServiceVisit document has invalid shape")
    if completed_at is not None and not isinstance(completed_at, datetime):
        raise ValueError("completed_at must be datetime or None")
    if technician_raw is not None and not isinstance(technician_raw, str):
        raise ValueError("completed_by_technician_id must be str or None")
    if event_raw is not None and not isinstance(event_raw, str):
        raise ValueError("maintenance_event_id must be str or None")
    loading_order_id = document.get("loading_order_id")
    if loading_order_id is not None and not isinstance(loading_order_id, str):
        raise ValueError("loading_order_id must be str or None")
    sources_raw = document.get("sources", [])
    if sources_raw is None:
        sources_raw = []
    if not isinstance(sources_raw, list):
        raise ValueError("sources must be a list")
    sources = frozenset(VisitTaskSource(item) for item in sources_raw if isinstance(item, str))
    return ServiceVisit(
        visit_id=visit_id,
        machine_id=MachineId(machine_id),
        kind=VisitKind(kind),
        due_date=_date_from_document(due_date),
        status=VisitStatus(status),
        closable=closable,
        priority_boost=priority_boost,
        incident_source=_optional_incident_source(document.get("incident_source")),
        close_type=_optional_close_type(document.get("close_type")),
        completed_at=None if completed_at is None else _as_utc(completed_at),
        completed_by_technician_id=(
            None if technician_raw is None else TechnicianId(technician_raw)
        ),
        maintenance_event_id=None if event_raw is None else EventId(event_raw),
        created_at=_as_utc(created_at),
        updated_at=_as_utc(updated_at),
        sources=sources,
        loading_order_id=loading_order_id,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoServiceVisitStore:
    _collection: ServiceVisitCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        visits: ServiceVisitsSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoServiceVisitStore:
        collection = resolve_collection(
            mongo,
            collection_name=visits.visits_collection,
            owner="MongoServiceVisitStore",
            client=client,
        )
        store = cls(collection)
        store.ensure_indexes()
        return store

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("machine_id", ASCENDING), ("status", ASCENDING)],
            name="service_visits_machine_status",
        )
        self._collection.create_index(
            [
                ("kind", ASCENDING),
                ("status", ASCENDING),
                ("incident_source", ASCENDING),
            ],
            name="service_visits_kind_status_incident_source",
        )
        self._collection.create_index(
            [("due_date", ASCENDING)],
            name="service_visits_due_date",
        )

    @beartype
    def upsert(self, visit: ServiceVisit) -> None:
        self._collection.replace_one(
            {"_id": visit.visit_id},
            service_visit_to_document(visit),
            upsert=True,
        )

    @beartype
    def get(self, visit_id: str) -> ServiceVisit | None:
        document = self._collection.find_one({"_id": visit_id})
        if document is None:
            return None
        return service_visit_from_document(document)

    @beartype
    def delete(self, visit_id: str) -> None:
        self._collection.delete_one({"_id": visit_id})

    @beartype
    def list_for_machine(
        self,
        machine_id: MachineId,
        *,
        status: VisitStatus | None = None,
    ) -> list[ServiceVisit]:
        query: dict[str, Any] = {"machine_id": machine_id.value}
        if status is not None:
            query["status"] = status.value
        items: list[ServiceVisit] = []
        for document in self._collection.find(query):
            if isinstance(document, dict):
                items.append(service_visit_from_document(document))
        items.sort(key=lambda visit: (visit.due_date, visit.visit_id))
        return items

    @beartype
    def list_open_extras(
        self,
        *,
        incident_source: IncidentSource | None = None,
    ) -> list[ServiceVisit]:
        query: dict[str, Any] = {
            "kind": VisitKind.EXTRA_INCIDENT.value,
            "status": VisitStatus.OPEN.value,
        }
        if incident_source is not None:
            query["incident_source"] = incident_source.value
        items: list[ServiceVisit] = []
        for document in self._collection.find(query):
            if isinstance(document, dict):
                items.append(service_visit_from_document(document))
        items.sort(key=lambda visit: (visit.due_date, visit.visit_id))
        return items

    @beartype
    def list_for_due_date_range(
        self,
        *,
        start: date,
        end: date,
    ) -> list[ServiceVisit]:
        query: dict[str, Any] = {
            "due_date": {
                "$gte": _date_to_utc_midnight(start),
                "$lte": _date_to_utc_midnight(end),
            }
        }
        items: list[ServiceVisit] = []
        for document in self._collection.find(query):
            if isinstance(document, dict):
                items.append(service_visit_from_document(document))
        items.sort(key=lambda visit: (visit.due_date, visit.visit_id))
        return items
