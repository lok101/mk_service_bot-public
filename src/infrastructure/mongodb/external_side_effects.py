from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.form_submissions.ports import (
    ExternalSideEffectClaim,
    ExternalSideEffectRegistry,
    ExternalSideEffectStatus,
)
from src.config.mongodb import MongoSettings
from src.infrastructure.external_side_effect_lease import (
    DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS,
    stale_processing_cutoff,
)
from src.infrastructure.mongodb.connection import resolve_collection


@runtime_checkable
class ExternalSideEffectsCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def find_one_and_update(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        return_document: bool = False,
    ) -> dict[str, Any] | None: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> object: ...

    def delete_many(self, filter: dict[str, Any]) -> object: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...


@beartype
def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
@dataclass(frozen=True, slots=True)
class MongoExternalSideEffectRegistry(ExternalSideEffectRegistry):
    _collection: ExternalSideEffectsCollection
    processing_lease_seconds: int = DEFAULT_EXTERNAL_SIDE_EFFECT_PROCESSING_LEASE_SECONDS

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: ExternalSideEffectsCollection,
    ) -> MongoExternalSideEffectRegistry:
        registry = cls(_collection=collection)
        registry.ensure_indexes()
        return registry

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoExternalSideEffectRegistry:
        collection = resolve_collection(
            settings,
            collection_name=settings.external_side_effects_collection,
            owner="MongoExternalSideEffectRegistry",
            client=client,
        )
        return cls.from_collection(collection)

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("provider", ASCENDING), ("operation", ASCENDING), ("idempotency_key", ASCENDING)],
            unique=True,
            name="external_side_effect_unique",
        )
        self._collection.create_index(
            [("status", ASCENDING), ("updated_at", ASCENDING)],
            name="external_side_effect_status",
        )

    @beartype
    def claim(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        external_code: str,
    ) -> ExternalSideEffectClaim:
        now = _utc_now()
        document = {
            "provider": provider,
            "operation": operation,
            "idempotency_key": idempotency_key,
            "external_code": external_code,
            "status": "processing",
            "external_id": None,
            "last_error": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self._collection.insert_one(document)
            return ExternalSideEffectClaim(
                claimed=True,
                status="processing",
                external_code=external_code,
            )
        except DuplicateKeyError:
            return self._claim_existing(
                provider=provider,
                operation=operation,
                idempotency_key=idempotency_key,
            )

    @beartype
    def _claim_existing(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
    ) -> ExternalSideEffectClaim:
        key_filter = _key_filter(
            provider=provider,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        document = self._collection.find_one_and_update(
            {
                **key_filter,
                "status": "failed",
            },
            {
                "$set": {
                    "status": "processing",
                    "last_error": None,
                    "updated_at": _utc_now(),
                },
            },
            return_document=True,
        )
        if document is not None:
            return _claim_from_document(document, claimed=True, previous_status="failed")

        cutoff = stale_processing_cutoff(
            now=_utc_now(),
            processing_lease_seconds=self.processing_lease_seconds,
        )
        reclaimed = self._collection.find_one_and_update(
            {
                **key_filter,
                "status": "processing",
                "updated_at": {"$lte": cutoff},
            },
            {
                "$set": {
                    "status": "processing",
                    "last_error": None,
                    "updated_at": _utc_now(),
                },
            },
            return_document=True,
        )
        if reclaimed is not None:
            return _claim_from_document(
                reclaimed,
                claimed=True,
                previous_status="processing",
            )

        existing = self._collection.find_one(key_filter)
        if existing is None:
            raise ValueError(
                "External side effect duplicate key was raised but document was not found",
            )
        return _claim_from_document(existing, claimed=False, previous_status=None)

    @beartype
    def mark_succeeded(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        external_id: str | None = None,
    ) -> None:
        result = self._collection.update_one(
            _key_filter(
                provider=provider,
                operation=operation,
                idempotency_key=idempotency_key,
            ),
            {
                "$set": {
                    "status": "succeeded",
                    "external_id": external_id,
                    "last_error": None,
                    "updated_at": _utc_now(),
                },
            },
        )
        _require_matched(result, operation=operation, idempotency_key=idempotency_key)

    @beartype
    def mark_failed(
        self,
        *,
        provider: str,
        operation: str,
        idempotency_key: str,
        error_message: str,
    ) -> None:
        result = self._collection.update_one(
            _key_filter(
                provider=provider,
                operation=operation,
                idempotency_key=idempotency_key,
            ),
            {
                "$set": {
                    "status": "failed",
                    "last_error": error_message,
                    "updated_at": _utc_now(),
                },
            },
        )
        _require_matched(result, operation=operation, idempotency_key=idempotency_key)

    @beartype
    def count_settlement_related(self) -> int:
        return int(
            self._collection.count_documents(
                {
                    "$or": [
                        {
                            "provider": "google_sheets",
                            "operation": "settlement_audit_row",
                        },
                        {
                            "provider": "moysklad",
                            "external_code": {"$regex": r"^mk-service-bot:settlement:"},
                        },
                    ],
                },
            ),
        )

    @beartype
    def delete_settlement_related(self) -> int:
        result = self._collection.delete_many(
            {
                "$or": [
                    {
                        "provider": "google_sheets",
                        "operation": "settlement_audit_row",
                    },
                    {
                        "provider": "moysklad",
                        "external_code": {"$regex": r"^mk-service-bot:settlement:"},
                    },
                ],
            },
        )
        return int(getattr(result, "deleted_count", 0))


@beartype
def _require_matched(result: object, *, operation: str, idempotency_key: str) -> None:
    matched_count = getattr(result, "matched_count", 0)
    if not isinstance(matched_count, int) or matched_count == 0:
        raise ValueError(
            f"External side effect {operation!r} for idempotency_key {idempotency_key!r} "
            "was not found while updating status",
        )


@beartype
def _key_filter(
    *,
    provider: str,
    operation: str,
    idempotency_key: str,
) -> dict[str, str]:
    return {
        "provider": provider,
        "operation": operation,
        "idempotency_key": idempotency_key,
    }


@beartype
def _claim_from_document(
    document: dict[str, Any],
    *,
    claimed: bool,
    previous_status: ExternalSideEffectStatus | None,
) -> ExternalSideEffectClaim:
    status = _status_from_document(document)
    external_code = document.get("external_code")
    if not isinstance(external_code, str) or not external_code:
        raise ValueError("External side effect external_code is invalid")
    external_id = document.get("external_id")
    return ExternalSideEffectClaim(
        claimed=claimed,
        status=status,
        external_code=external_code,
        previous_status=previous_status,
        external_id=external_id if isinstance(external_id, str) else None,
    )


@beartype
def _status_from_document(document: dict[str, Any]) -> ExternalSideEffectStatus:
    status = document.get("status")
    if status not in {"processing", "succeeded", "failed"}:
        raise ValueError("External side effect status is invalid")
    return cast(ExternalSideEffectStatus, status)
