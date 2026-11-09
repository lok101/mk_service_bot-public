from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, SupportsIndex, SupportsInt, runtime_checkable

from beartype import beartype
from pymongo import MongoClient

from src.application.master_data import SystemUserAuditRecord, SystemUserRecord
from src.config.master_data import MasterDataSettings
from src.config.mongodb import MongoSettings
from src.domain.ids import TechnicianId
from src.domain.system_user import (
    AdminPanel,
    BotRole,
    CompanyRole,
    SystemUser,
    SystemUserId,
    company_roles_from_legacy_panels,
)
from src.infrastructure.mongodb.connection import MongoDatabaseSource, resolve_collection

PLANOGRAM_PANEL_BACKFILL_ID = "planogram-panel-backfill"


@runtime_checkable
class SystemUsersCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find(self, filter: dict[str, Any], **kwargs: Any) -> Any: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def delete_many(self, filter: dict[str, Any]) -> Any: ...

    def update_one(self, filter: dict[str, Any], update: dict[str, Any]) -> Any: ...

    def insert_one(self, document: dict[str, Any]) -> Any: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@runtime_checkable
class SystemUsersAuditCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> Any: ...

    def find(self, filter: dict[str, Any]) -> Any: ...


@beartype
def _coerce_telegram_user_id(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if type(raw) is int:
        return raw
    if not isinstance(raw, (str, bytes, bytearray, SupportsInt, SupportsIndex)):
        return None
    try:
        value = int(raw)
    except TypeError, ValueError, OverflowError:
        return None
    if value <= 0:
        return None
    return value


@beartype
def _is_user_document_id(raw: object) -> bool:
    return _coerce_telegram_user_id(raw) is not None


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _record_to_document(record: SystemUserRecord) -> dict[str, Any]:
    user = record.user
    return {
        "_id": user.telegram_user_id,
        "user_id": user.user_id.value,
        "name": user.name,
        "is_active": user.is_active,
        "bot_role": user.role.value,
        "technician_id": None if user.technician_id is None else user.technician_id.value,
        "company_roles": sorted(role.value for role in user.company_roles),
        "updated_at": _as_utc(record.updated_at),
        "updated_by_telegram_user_id": record.updated_by_telegram_user_id,
    }


@beartype
def _record_payload(record: SystemUserRecord) -> dict[str, Any]:
    document = _record_to_document(record)
    document["telegram_user_id"] = record.user.telegram_user_id
    document.pop("_id", None)
    return document


@beartype
def _panels_from_document(value: object) -> frozenset[AdminPanel]:
    if not isinstance(value, list):
        raise ValueError("panels must be a list")
    panels: list[AdminPanel] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("panels items must be str")
        panels.append(AdminPanel(item))
    return frozenset(panels)


@beartype
def _company_roles_from_document(value: object) -> frozenset[CompanyRole]:
    if not isinstance(value, list):
        raise ValueError("company_roles must be a list")
    roles: list[CompanyRole] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("company_roles items must be str")
        try:
            roles.append(CompanyRole(item))
        except ValueError as error:
            raise ValueError(f"unknown company role: {item!r}") from error
    return frozenset(roles)


@beartype
def _company_roles_from_user_document(document: dict[str, Any]) -> frozenset[CompanyRole]:
    if "company_roles" in document:
        return _company_roles_from_document(document["company_roles"])
    if "panels" in document:
        return company_roles_from_legacy_panels(_panels_from_document(document["panels"]))
    raise ValueError("document must contain company_roles or legacy panels")


@beartype
def _record_from_document(document: dict[str, Any]) -> SystemUserRecord:
    telegram_raw = document.get("_id", document.get("telegram_user_id"))
    user_id_raw = document.get("user_id")
    name = document.get("name")
    is_active = document.get("is_active")
    role_raw = document.get("bot_role")
    technician_raw = document.get("technician_id")
    updated_at = document.get("updated_at")
    actor_id = document.get("updated_by_telegram_user_id")
    telegram_user_id = _coerce_telegram_user_id(telegram_raw)
    if telegram_user_id is None:
        raise ValueError("telegram_user_id must be int")
    if not isinstance(user_id_raw, str):
        raise ValueError("user_id must be str")
    if not isinstance(name, str):
        raise ValueError("name must be str")
    if not isinstance(is_active, bool):
        raise ValueError("is_active must be bool")
    if not isinstance(role_raw, str):
        raise ValueError("bot_role must be str")
    if technician_raw is not None and not isinstance(technician_raw, str):
        raise ValueError("technician_id must be str or None")
    if not isinstance(updated_at, datetime):
        raise ValueError("updated_at must be datetime")
    actor_telegram_user_id = _coerce_telegram_user_id(actor_id)
    if actor_telegram_user_id is None:
        raise ValueError("updated_by_telegram_user_id must be int")
    return SystemUserRecord(
        user=SystemUser(
            user_id=SystemUserId(user_id_raw),
            name=name,
            role=BotRole(role_raw),
            is_active=is_active,
            telegram_user_id=telegram_user_id,
            technician_id=None if technician_raw is None else TechnicianId(technician_raw),
            company_roles=_company_roles_from_user_document(document),
        ),
        updated_at=_as_utc(updated_at),
        updated_by_telegram_user_id=actor_telegram_user_id,
    )


@beartype
def _optional_record(value: object) -> SystemUserRecord | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("audit before/after must be dict or None")
    return _record_from_document(value)


@beartype
def _audit_from_document(document: dict[str, Any]) -> SystemUserAuditRecord:
    at = document.get("at")
    actor_id = document.get("actor_telegram_user_id")
    audit_command = document.get("audit_command")
    telegram_raw = document.get("telegram_user_id")
    if not isinstance(at, datetime):
        raise ValueError("audit at must be datetime")
    if not isinstance(actor_id, int) or isinstance(actor_id, bool):
        raise ValueError("actor_telegram_user_id must be int")
    if not isinstance(audit_command, str):
        raise ValueError("audit_command must be str")
    if not isinstance(telegram_raw, int) or isinstance(telegram_raw, bool):
        raise ValueError("telegram_user_id must be int")
    return SystemUserAuditRecord(
        at=_as_utc(at),
        actor_telegram_user_id=actor_id,
        audit_command=audit_command,
        telegram_user_id=telegram_raw,
        before=_optional_record(document.get("before")),
        after=_optional_record(document.get("after")),
    )


@beartype
@dataclass(frozen=True, slots=True)
class MongoSystemUserStore:
    users_collection: SystemUsersCollection
    audit_collection: SystemUsersAuditCollection

    @classmethod
    @beartype
    def from_settings(
        cls,
        mongo: MongoSettings,
        master_data: MasterDataSettings,
        *,
        client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    ) -> MongoSystemUserStore:
        users_collection = resolve_collection(
            mongo,
            collection_name=master_data.system_users_collection,
            owner="MongoSystemUserStore",
            client=client,
        )
        audit_collection = resolve_collection(
            mongo,
            collection_name=master_data.audit_collection,
            owner="MongoSystemUserStore",
            client=client,
        )
        store = cls(
            users_collection=users_collection,
            audit_collection=audit_collection,
        )
        store.ensure_indexes()
        return store

    @beartype
    def ensure_indexes(self) -> None:
        self.users_collection.create_index(
            [("is_active", 1)],
            name="user_is_active",
        )

    @beartype
    def get(self, telegram_user_id: int) -> SystemUserRecord | None:
        document = self.users_collection.find_one({"_id": telegram_user_id})
        if document is None:
            return None
        return _record_from_document(document)

    @beartype
    def list_all(self) -> tuple[SystemUserRecord, ...]:
        items: list[SystemUserRecord] = []
        for document in self.users_collection.find({}):
            if not isinstance(document, dict):
                continue
            if not _is_user_document_id(document.get("_id")):
                continue
            items.append(_record_from_document(document))
        items.sort(key=lambda record: record.user.telegram_user_id)
        return tuple(items)

    @beartype
    def is_empty(self) -> bool:
        return not any(
            _is_user_document_id(doc.get("_id"))
            for doc in self.users_collection.find({}, projection={"_id": 1})
            if isinstance(doc, dict)
        )

    @beartype
    def replace_all(self, records: tuple[SystemUserRecord, ...]) -> None:
        user_ids = [
            document["_id"]
            for document in self.users_collection.find({}, projection={"_id": 1})
            if isinstance(document, dict) and _is_user_document_id(document.get("_id"))
        ]
        if user_ids:
            self.users_collection.delete_many({"_id": {"$in": user_ids}})
        for record in records:
            self.users_collection.replace_one(
                {"_id": record.user.telegram_user_id},
                _record_to_document(record),
                upsert=True,
            )

    @beartype
    def grant_planogram_panel_once(self) -> None:
        if self.users_collection.find_one({"_id": PLANOGRAM_PANEL_BACKFILL_ID}) is not None:
            return
        for document in self.users_collection.find({}):
            if not isinstance(document, dict):
                continue
            raw_id = document.get("_id")
            if not _is_user_document_id(raw_id):
                continue
            panels = document.get("panels")
            if not isinstance(panels, list) or "master_data" not in panels:
                continue
            if "micromarket_planograms" in panels:
                continue
            updated = sorted([*panels, "micromarket_planograms"])
            self.users_collection.update_one({"_id": raw_id}, {"$set": {"panels": updated}})
        self.users_collection.insert_one({"_id": PLANOGRAM_PANEL_BACKFILL_ID})

    @beartype
    def save_batch(
        self,
        records: tuple[SystemUserRecord, ...],
        *,
        actor_telegram_user_id: int,
        at: datetime,
        audit_command: str,
    ) -> None:
        incoming = {record.user.telegram_user_id: record for record in records}
        existing = {record.user.telegram_user_id: record for record in self.list_all()}
        for telegram_user_id, record in incoming.items():
            before = existing.get(telegram_user_id)
            self.users_collection.replace_one(
                {"_id": telegram_user_id},
                _record_to_document(record),
                upsert=True,
            )
            self.audit_collection.insert_one(
                {
                    "at": _as_utc(at),
                    "actor_telegram_user_id": actor_telegram_user_id,
                    "audit_command": audit_command,
                    "telegram_user_id": telegram_user_id,
                    "before": None if before is None else _record_payload(before),
                    "after": _record_payload(record),
                },
            )

    @beartype
    def list_audit(self) -> tuple[SystemUserAuditRecord, ...]:
        documents = [
            document for document in self.audit_collection.find({}) if isinstance(document, dict)
        ]
        documents.sort(key=lambda document: str(document.get("_id", "")))
        return tuple(_audit_from_document(document) for document in documents)
