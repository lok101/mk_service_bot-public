from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from beartype import beartype
from pymongo import MongoClient

from src.config.mongodb import MongoSettings
from src.domain.calendar import operational_day
from src.domain.maintenance_cooldown_bypass import MaintenanceCooldownBypassSnapshot
from src.domain.maintenance_cooldown_policy import is_maintenance_cooldown_bypassed
from src.infrastructure.mongodb.connection import resolve_collection

_GLOBAL_DOCUMENT_ID = "global"


@runtime_checkable
class MaintenanceCooldownBypassCollection(Protocol):
    def replace_one(
        self,
        filter: dict[str, Any],
        replacement: dict[str, Any],
        *,
        upsert: bool = False,
    ) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def delete_one(self, filter: dict[str, Any]) -> Any: ...


@beartype
def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


@beartype
def snapshot_to_document(snapshot: MaintenanceCooldownBypassSnapshot) -> dict[str, Any]:
    return {
        "_id": _GLOBAL_DOCUMENT_ID,
        "service_date": snapshot.service_date.isoformat(),
        "activated_at": snapshot.activated_at,
        "reason": snapshot.reason,
    }


@beartype
def snapshot_from_document(document: dict[str, Any]) -> MaintenanceCooldownBypassSnapshot:
    service_date_raw = document["service_date"]
    if not isinstance(service_date_raw, str):
        raise ValueError("maintenance cooldown bypass service_date is invalid")
    return MaintenanceCooldownBypassSnapshot(
        service_date=date.fromisoformat(service_date_raw),
        activated_at=_ensure_aware(document["activated_at"]),
        reason=document.get("reason"),
    )


@beartype
@dataclass(slots=True)
class MongoMaintenanceCooldownBypassStore:
    _collection: MaintenanceCooldownBypassCollection
    service_calendar_timezone: ZoneInfo
    service_day_end_hour: int

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
        service_calendar_timezone: ZoneInfo,
        service_day_end_hour: int,
    ) -> MongoMaintenanceCooldownBypassStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.maintenance_cooldown_bypass_collection,
            owner="MongoMaintenanceCooldownBypassStore",
            client=client,
        )
        return cls(
            _collection=collection,
            service_calendar_timezone=service_calendar_timezone,
            service_day_end_hour=service_day_end_hour,
        )

    @beartype
    def get_snapshot(self) -> MaintenanceCooldownBypassSnapshot | None:
        document = self._collection.find_one({"_id": _GLOBAL_DOCUMENT_ID})
        if document is None:
            return None
        return snapshot_from_document(document)

    @beartype
    def upsert_for_today(
        self,
        *,
        activated_at: datetime,
        reason: str | None,
        service_calendar_timezone: ZoneInfo,
    ) -> MaintenanceCooldownBypassSnapshot:
        service_date = operational_day(
            activated_at,
            service_calendar_timezone,
            self.service_day_end_hour,
        )
        snapshot = MaintenanceCooldownBypassSnapshot(
            service_date=service_date,
            activated_at=activated_at,
            reason=reason,
        )
        self._collection.replace_one(
            {"_id": _GLOBAL_DOCUMENT_ID},
            snapshot_to_document(snapshot),
            upsert=True,
        )
        return snapshot

    @beartype
    def get_active(
        self,
        *,
        checked_at: datetime | None = None,
    ) -> MaintenanceCooldownBypassSnapshot | None:
        snapshot = self.get_snapshot()
        if snapshot is None:
            return None
        effective_checked_at = checked_at or datetime.now(tz=UTC)
        if is_maintenance_cooldown_bypassed(
            checked_at=effective_checked_at,
            bypass_service_date=snapshot.service_date,
            service_calendar_timezone=self.service_calendar_timezone,
            day_end_hour=self.service_day_end_hour,
        ):
            return snapshot
        return None

    @beartype
    def clear(self) -> bool:
        result = self._collection.delete_one({"_id": _GLOBAL_DOCUMENT_ID})
        deleted_count = getattr(result, "deleted_count", 0)
        return isinstance(deleted_count, int) and deleted_count > 0
