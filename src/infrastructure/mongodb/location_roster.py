from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.reference_data.location_roster import (
    LocationRosterAuditRecord,
    LocationRosterEntry,
)
from src.config.location_roster import LocationRosterSettings
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId, TechnicianId
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class LocationRosterCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def insert_one(self, document: dict[str, Any]) -> Any: ...

    def delete_many(self, filter: dict[str, Any]) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...


@runtime_checkable
class LocationRosterAuditCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> Any: ...

    def find(self, filter: dict[str, Any]) -> Any: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    # BSON Date is millisecond precision; keep tokens aligned with storage.
    return aware.replace(microsecond=(aware.microsecond // 1000) * 1000)


@beartype
def _entry_to_document(entry: LocationRosterEntry) -> dict[str, Any]:
    return {
        "_id": entry.machine_id.value,
        "technician_id": None if entry.technician_id is None else entry.technician_id.value,
        "service_weekdays": sorted(entry.service_weekdays),
        "updated_at": _as_utc(entry.updated_at),
        "updated_by_telegram_user_id": entry.updated_by_telegram_user_id,
    }


@beartype
def _entry_payload(entry: LocationRosterEntry) -> dict[str, Any]:
    document = _entry_to_document(entry)
    document["machine_id"] = entry.machine_id.value
    document.pop("_id", None)
    return document


@beartype
def _weekdays_from_document(value: object) -> frozenset[int]:
    if not isinstance(value, list):
        raise ValueError("service_weekdays must be a list")
    weekdays: list[int] = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool):
            raise ValueError("service_weekdays items must be int")
        weekdays.append(item)
    return frozenset(weekdays)


@beartype
def _entry_from_mapping(document: dict[str, Any], *, machine_id: MachineId) -> LocationRosterEntry:
    technician_raw = document.get("technician_id")
    updated_at = document.get("updated_at")
    actor_id = document.get("updated_by_telegram_user_id")
    if technician_raw is not None and not isinstance(technician_raw, str):
        raise ValueError("technician_id must be str or None")
    if not isinstance(updated_at, datetime):
        raise ValueError("updated_at must be datetime")
    if not isinstance(actor_id, int) or isinstance(actor_id, bool):
        raise ValueError("updated_by_telegram_user_id must be int")
    return LocationRosterEntry(
        machine_id=machine_id,
        technician_id=None if technician_raw is None else TechnicianId(technician_raw),
        service_weekdays=_weekdays_from_document(document.get("service_weekdays")),
        updated_at=_as_utc(updated_at),
        updated_by_telegram_user_id=actor_id,
    )


@beartype
def _entry_from_document(document: dict[str, Any]) -> LocationRosterEntry:
    machine_raw = document.get("machine_id", document.get("_id"))
    if not isinstance(machine_raw, str):
        raise ValueError("machine_id must be str")
    return _entry_from_mapping(document, machine_id=MachineId(machine_raw))


@beartype
def _optional_entry(value: object) -> LocationRosterEntry | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("audit before/after must be dict or None")
    return _entry_from_document(value)


@beartype
def _audit_from_document(document: dict[str, Any]) -> LocationRosterAuditRecord:
    at = document.get("at")
    actor_id = document.get("actor_telegram_user_id")
    machine_raw = document.get("machine_id")
    if not isinstance(at, datetime):
        raise ValueError("audit at must be datetime")
    if not isinstance(actor_id, int) or isinstance(actor_id, bool):
        raise ValueError("actor_telegram_user_id must be int")
    if not isinstance(machine_raw, str):
        raise ValueError("audit machine_id must be str")
    after = document.get("after")
    if not isinstance(after, dict):
        raise ValueError("audit after must be dict")
    return LocationRosterAuditRecord(
        at=_as_utc(at),
        actor_telegram_user_id=actor_id,
        machine_id=MachineId(machine_raw),
        before=_optional_entry(document.get("before")),
        after=_entry_from_document(after),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoLocationRosterStore:
    roster_collection: LocationRosterCollection
    audit_collection: LocationRosterAuditCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        roster: LocationRosterSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoLocationRosterStore:
        roster_collection = resolve_collection(
            mongo,
            collection_name=roster.roster_collection,
            owner="MongoLocationRosterStore",
            client=client,
        )
        audit_collection = resolve_collection(
            mongo,
            collection_name=roster.audit_collection,
            owner="MongoLocationRosterStore",
            client=client,
        )
        return cls(
            roster_collection=roster_collection,
            audit_collection=audit_collection,
        )

    @beartype
    def get(self, machine_id: MachineId) -> LocationRosterEntry | None:
        document = self.roster_collection.find_one({"_id": machine_id.value})
        if document is None:
            return None
        return _entry_from_document(document)

    @beartype
    def list_all(self) -> tuple[LocationRosterEntry, ...]:
        items: list[LocationRosterEntry] = []
        for document in self.roster_collection.find({}):
            if isinstance(document, dict):
                items.append(_entry_from_document(document))
        items.sort(key=lambda entry: entry.machine_id.value)
        return tuple(items)

    @beartype
    def is_empty(self) -> bool:
        return int(self.roster_collection.count_documents({})) == 0

    @beartype
    def replace_all(self, entries: tuple[LocationRosterEntry, ...]) -> None:
        for entry in entries:
            self.roster_collection.replace_one(
                {"_id": entry.machine_id.value},
                _entry_to_document(entry),
                upsert=True,
            )

    @beartype
    def save_batch(
        self,
        entries: tuple[LocationRosterEntry, ...],
        *,
        actor_telegram_user_id: int,
        at: datetime,
    ) -> None:
        for entry in entries:
            before = self.get(entry.machine_id)
            self.roster_collection.replace_one(
                {"_id": entry.machine_id.value},
                _entry_to_document(entry),
                upsert=True,
            )
            self.audit_collection.insert_one(
                {
                    "at": _as_utc(at),
                    "actor_telegram_user_id": actor_telegram_user_id,
                    "machine_id": entry.machine_id.value,
                    "before": None if before is None else _entry_payload(before),
                    "after": _entry_payload(entry),
                },
            )

    @beartype
    def list_audit(self) -> tuple[LocationRosterAuditRecord, ...]:
        documents = [
            document for document in self.audit_collection.find({}) if isinstance(document, dict)
        ]
        documents.sort(key=lambda document: str(document["_id"]))
        return tuple(_audit_from_document(document) for document in documents)
