from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import MongoClient, ReturnDocument

from src.application.master_data import (
    MachineKind,
    MachineStatus,
    MasterDataAuditRecord,
    MasterLocation,
    MasterMachine,
    MasterPlacement,
    OpenPlacementExists,
)
from src.config.master_data import MasterDataSettings
from src.config.mongodb import MongoSettings
from src.domain.ids import MachineId
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection


@runtime_checkable
class MasterDataCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def insert_one(self, document: dict[str, Any]) -> Any: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...

    def find_one_and_update(
        self,
        filter: dict[str, Any],
        update: dict[str, Any] | list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any] | None: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _optional_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"invalid decimal: {value!r}") from exc
    raise ValueError(f"latitude/longitude must be Decimal-compatible, got {type(value)!r}")


@beartype
def _location_to_document(location: MasterLocation) -> dict[str, Any]:
    return {
        "_id": location.location_id,
        "name": location.name,
        "city": location.city,
        "street": location.street,
        "house": location.house,
        "display_name": location.display_name,
        "latitude": None if location.latitude is None else str(location.latitude),
        "longitude": None if location.longitude is None else str(location.longitude),
    }


@beartype
def _location_from_document(document: dict[str, Any]) -> MasterLocation:
    location_id = document.get("_id", document.get("location_id"))
    display_name = document.get("display_name")
    if not isinstance(location_id, str):
        raise ValueError("location_id must be str")
    if not isinstance(display_name, str):
        raise ValueError("display_name must be str")

    def _str_field(key: str) -> str:
        raw = document.get(key, "")
        if raw is None:
            return ""
        if not isinstance(raw, str):
            raise ValueError(f"{key} must be str")
        return raw

    return MasterLocation(
        location_id=location_id,
        name=_str_field("name"),
        city=_str_field("city"),
        street=_str_field("street"),
        house=_str_field("house"),
        display_name=display_name,
        latitude=_optional_decimal(document.get("latitude")),
        longitude=_optional_decimal(document.get("longitude")),
    )


@beartype
def _machine_to_document(machine: MasterMachine) -> dict[str, Any]:
    return {
        "_id": machine.machine_id.value,
        "kind": machine.kind.value,
        "status": machine.status.value,
        "label": machine.label,
        "include_in_no_sales_monitoring": machine.include_in_no_sales_monitoring,
        "create_visit_on_no_sales": machine.create_visit_on_no_sales,
        "include_in_visit_photo_review": machine.include_in_visit_photo_review,
        "coffee_machine_model_id": machine.coffee_machine_model_id,
        "stand_type_id": machine.stand_type_id,
        "stand_color_id": machine.stand_color_id,
    }


@beartype
def _machine_from_document(document: dict[str, Any]) -> MasterMachine:
    machine_raw = document.get("_id", document.get("machine_id"))
    kind_raw = document.get("kind")
    status_raw = document.get("status")
    label = document.get("label")
    include = document.get("include_in_no_sales_monitoring", True)
    create_visit = document.get("create_visit_on_no_sales", True)
    include_in_visit_photo_review = document.get("include_in_visit_photo_review", True)
    if not isinstance(machine_raw, str):
        raise ValueError("machine_id must be str")
    if not isinstance(kind_raw, str):
        raise ValueError("kind must be str")
    if not isinstance(status_raw, str):
        raise ValueError("status must be str")
    if label is not None and not isinstance(label, str):
        raise ValueError("label must be str or None")
    if not isinstance(include, bool):
        raise ValueError("include_in_no_sales_monitoring must be bool")
    if not isinstance(create_visit, bool):
        raise ValueError("create_visit_on_no_sales must be bool")
    if not isinstance(include_in_visit_photo_review, bool):
        raise ValueError("include_in_visit_photo_review must be bool")
    coffee_machine_model_id = _optional_catalog_id(
        document.get("coffee_machine_model_id"),
        field="coffee_machine_model_id",
    )
    stand_type_id = _optional_catalog_id(document.get("stand_type_id"), field="stand_type_id")
    stand_color_id = _optional_catalog_id(document.get("stand_color_id"), field="stand_color_id")
    return MasterMachine(
        machine_id=MachineId(machine_raw),
        kind=MachineKind(kind_raw),
        status=MachineStatus(status_raw),
        label=label,
        include_in_no_sales_monitoring=include,
        create_visit_on_no_sales=create_visit,
        include_in_visit_photo_review=include_in_visit_photo_review,
        coffee_machine_model_id=coffee_machine_model_id,
        stand_type_id=stand_type_id,
        stand_color_id=stand_color_id,
    )


@beartype
def _optional_catalog_id(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be str or None")
    return value


@beartype
def _placement_to_document(placement: MasterPlacement) -> dict[str, Any]:
    return {
        "_id": placement.placement_id,
        "machine_id": placement.machine_id.value,
        "location_id": placement.location_id,
        "valid_from": _as_utc(placement.valid_from),
        "valid_to": None if placement.valid_to is None else _as_utc(placement.valid_to),
    }


@beartype
def _placement_from_document(document: dict[str, Any]) -> MasterPlacement:
    placement_id = document.get("_id", document.get("placement_id"))
    machine_raw = document.get("machine_id")
    location_id = document.get("location_id")
    valid_from = document.get("valid_from")
    valid_to = document.get("valid_to")
    if not isinstance(placement_id, str):
        raise ValueError("placement_id must be str")
    if not isinstance(machine_raw, str):
        raise ValueError("machine_id must be str")
    if not isinstance(location_id, str):
        raise ValueError("location_id must be str")
    if not isinstance(valid_from, datetime):
        raise ValueError("valid_from must be datetime")
    if valid_to is not None and not isinstance(valid_to, datetime):
        raise ValueError("valid_to must be datetime or None")
    return MasterPlacement(
        placement_id=placement_id,
        machine_id=MachineId(machine_raw),
        location_id=location_id,
        valid_from=_as_utc(valid_from),
        valid_to=None if valid_to is None else _as_utc(valid_to),
    )


@beartype
def _audit_to_document(record: MasterDataAuditRecord) -> dict[str, Any]:
    return {
        "at": _as_utc(record.at),
        "actor_telegram_user_id": record.actor_telegram_user_id,
        "command": record.command,
        "payload": dict(record.payload),
    }


@beartype
def _audit_from_document(document: dict[str, Any]) -> MasterDataAuditRecord:
    at = document.get("at")
    actor_id = document.get("actor_telegram_user_id")
    command = document.get("command")
    payload = document.get("payload")
    if not isinstance(at, datetime):
        raise ValueError("audit at must be datetime")
    if not isinstance(actor_id, int) or isinstance(actor_id, bool):
        raise ValueError("actor_telegram_user_id must be int")
    if not isinstance(command, str):
        raise ValueError("command must be str")
    if not isinstance(payload, dict):
        raise ValueError("payload must be dict")
    typed_payload: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("payload must be dict[str, str]")
        typed_payload[key] = value
    return MasterDataAuditRecord(
        at=_as_utc(at),
        actor_telegram_user_id=actor_id,
        command=command,
        payload=typed_payload,
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMasterLocationStore:
    collection: MasterDataCollection

    @beartype
    def get(self, location_id: str) -> MasterLocation | None:
        document = self.collection.find_one({"_id": location_id})
        if document is None:
            return None
        return _location_from_document(document)

    @beartype
    def upsert(self, location: MasterLocation) -> None:
        self.collection.replace_one(
            {"_id": location.location_id},
            _location_to_document(location),
            upsert=True,
        )

    @beartype
    def delete(self, location_id: str) -> None:
        self.collection.delete_one({"_id": location_id})

    @beartype
    def list_all(self) -> tuple[MasterLocation, ...]:
        items: list[MasterLocation] = []
        for document in self.collection.find({}):
            if isinstance(document, dict):
                items.append(_location_from_document(document))
        items.sort(key=lambda loc: loc.location_id)
        return tuple(items)

    @beartype
    def is_empty(self) -> bool:
        return int(self.collection.count_documents({})) == 0


@beartype
@dataclass(frozen=True, slots=True)
class MongoMasterMachineStore:
    collection: MasterDataCollection

    @beartype
    def get(self, machine_id: MachineId) -> MasterMachine | None:
        document = self.collection.find_one({"_id": machine_id.value})
        if document is None:
            return None
        return _machine_from_document(document)

    @beartype
    def upsert(self, machine: MasterMachine) -> None:
        self.collection.replace_one(
            {"_id": machine.machine_id.value},
            _machine_to_document(machine),
            upsert=True,
        )

    @beartype
    def list_all(self) -> tuple[MasterMachine, ...]:
        items: list[MasterMachine] = []
        for document in self.collection.find({}):
            if isinstance(document, dict):
                items.append(_machine_from_document(document))
        items.sort(key=lambda machine: machine.machine_id.value)
        return tuple(items)

    @beartype
    def is_empty(self) -> bool:
        return int(self.collection.count_documents({})) == 0


@beartype
@dataclass(frozen=True, slots=True)
class MongoMasterPlacementStore:
    collection: MasterDataCollection

    @beartype
    def insert(self, placement: MasterPlacement) -> None:
        if placement.valid_to is None and self.get_open(placement.machine_id) is not None:
            raise OpenPlacementExists(
                f"open placement already exists for machine {placement.machine_id.value!r}",
            )
        self.collection.insert_one(_placement_to_document(placement))

    @beartype
    def update(self, placement: MasterPlacement) -> None:
        self.collection.replace_one(
            {"_id": placement.placement_id},
            _placement_to_document(placement),
            upsert=False,
        )

    @beartype
    def get_open(self, machine_id: MachineId) -> MasterPlacement | None:
        document = self.collection.find_one(
            {"machine_id": machine_id.value, "valid_to": None},
        )
        if document is None:
            return None
        return _placement_from_document(document)

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[MasterPlacement, ...]:
        items: list[MasterPlacement] = []
        for document in self.collection.find({"machine_id": machine_id.value}):
            if isinstance(document, dict):
                items.append(_placement_from_document(document))
        items.sort(key=lambda placement: placement.placement_id)
        return tuple(items)

    @beartype
    def list_all(self) -> tuple[MasterPlacement, ...]:
        items: list[MasterPlacement] = []
        for document in self.collection.find({}):
            if isinstance(document, dict):
                items.append(_placement_from_document(document))
        items.sort(key=lambda placement: placement.placement_id)
        return tuple(items)

    @beartype
    def is_empty(self) -> bool:
        return int(self.collection.count_documents({})) == 0

    @beartype
    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("machine_id", 1), ("valid_to", 1)],
            name="machine_id_valid_to",
        )


@beartype
@dataclass(frozen=True, slots=True)
class MongoMasterDataCounterStore:
    collection: MasterDataCollection

    @beartype
    def get(self, name: str) -> int:
        document = self.collection.find_one({"_id": name})
        if document is None:
            return 0
        value = document.get("value")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("counter value must be int")
        return value

    @beartype
    def set(self, name: str, value: int) -> None:
        self.collection.replace_one(
            {"_id": name},
            {"_id": name, "value": value},
            upsert=True,
        )

    @beartype
    def allocate_next(self, name: str) -> int:
        document = self.collection.find_one_and_update(
            {"_id": name},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise RuntimeError("counter find_one_and_update returned no document")
        value = document.get("value")
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("counter value must be int")
        return value


@beartype
@dataclass(frozen=True, slots=True)
class MongoMasterDataAuditStore:
    collection: MasterDataCollection

    @beartype
    def append(self, record: MasterDataAuditRecord) -> None:
        self.collection.insert_one(_audit_to_document(record))

    @beartype
    def list_all(self) -> tuple[MasterDataAuditRecord, ...]:
        documents = [
            document for document in self.collection.find({}) if isinstance(document, dict)
        ]
        documents.sort(key=lambda document: str(document.get("_id", "")))
        return tuple(_audit_from_document(document) for document in documents)


@beartype
@dataclass(frozen=True, slots=True)
class MongoMasterDataStores:
    locations: MongoMasterLocationStore
    machines: MongoMasterMachineStore
    placements: MongoMasterPlacementStore
    counters: MongoMasterDataCounterStore
    audit: MongoMasterDataAuditStore

    @classmethod
    @beartype
    def from_database(
        cls,
        database: Any,
        *,
        locations_collection: str,
        machines_collection: str,
        placements_collection: str,
        counters_collection: str,
        audit_collection: str,
    ) -> MongoMasterDataStores:
        stores = cls(
            locations=MongoMasterLocationStore(collection=database[locations_collection]),
            machines=MongoMasterMachineStore(collection=database[machines_collection]),
            placements=MongoMasterPlacementStore(collection=database[placements_collection]),
            counters=MongoMasterDataCounterStore(collection=database[counters_collection]),
            audit=MongoMasterDataAuditStore(collection=database[audit_collection]),
        )
        stores.placements.ensure_indexes()
        return stores

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        master_data: MasterDataSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoMasterDataStores:
        stores = cls(
            locations=MongoMasterLocationStore(
                collection=resolve_collection(
                    mongo,
                    collection_name=master_data.locations_collection,
                    owner="MongoMasterDataStores",
                    client=client,
                ),
            ),
            machines=MongoMasterMachineStore(
                collection=resolve_collection(
                    mongo,
                    collection_name=master_data.machines_collection,
                    owner="MongoMasterDataStores",
                    client=client,
                ),
            ),
            placements=MongoMasterPlacementStore(
                collection=resolve_collection(
                    mongo,
                    collection_name=master_data.placements_collection,
                    owner="MongoMasterDataStores",
                    client=client,
                ),
            ),
            counters=MongoMasterDataCounterStore(
                collection=resolve_collection(
                    mongo,
                    collection_name=master_data.counters_collection,
                    owner="MongoMasterDataStores",
                    client=client,
                ),
            ),
            audit=MongoMasterDataAuditStore(
                collection=resolve_collection(
                    mongo,
                    collection_name=master_data.audit_collection,
                    owner="MongoMasterDataStores",
                    client=client,
                ),
            ),
        )
        stores.placements.ensure_indexes()
        return stores
