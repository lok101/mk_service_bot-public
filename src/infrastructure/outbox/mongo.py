from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from beartype import beartype
from pymongo import ASCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from src.application.machine_operations.ports import OutboxStore
from src.application.outbox import SETTLEMENT_PORTION_HANDLER_IDS
from src.application.outbox.ports import FailedOutboxEntrySummary
from src.config.mongodb import MongoSettings
from src.infrastructure.mongodb.connection import resolve_collection
from src.infrastructure.outbox.memory import (
    DEFAULT_PROCESSING_LEASE_SECONDS,
    OUTBOX_STATUS_FAILED,
    OUTBOX_STATUS_PENDING,
    OUTBOX_STATUS_PROCESSED,
    OUTBOX_STATUS_PROCESSING,
    _stale_claim_cutoff,
)


@runtime_checkable
class OutboxCollection(Protocol):
    def insert_one(self, document: dict[str, Any]) -> object: ...

    def find_one_and_update(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
        *,
        sort: list[tuple[str, int]] | None = None,
        return_document: bool = False,
    ) -> dict[str, Any] | None: ...

    def update_one(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> object: ...

    def update_many(
        self,
        filter: dict[str, Any],
        update: dict[str, Any],
    ) -> object: ...

    def create_index(self, keys: str | list[tuple[str, int]], **kwargs: Any) -> str: ...

    def find(self, filter: dict[str, Any]) -> Any: ...

    def find_one(self, filter: dict[str, Any]) -> dict[str, Any] | None: ...

    def count_documents(self, filter: dict[str, Any]) -> int: ...


@beartype
def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
def _matched_count(result: object) -> int:
    matched_count = getattr(result, "matched_count", 0)
    return int(matched_count) if isinstance(matched_count, int) else 0


@beartype
@dataclass(frozen=True, slots=True)
class MongoOutboxStore(OutboxStore):
    _collection: OutboxCollection
    max_attempts: int
    processing_lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS

    @classmethod
    @beartype
    def from_collection(
        cls,
        collection: OutboxCollection,
        *,
        max_attempts: int,
        processing_lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS,
    ) -> MongoOutboxStore:
        store = cls(
            _collection=collection,
            max_attempts=max_attempts,
            processing_lease_seconds=processing_lease_seconds,
        )
        store.ensure_indexes()
        return store

    @classmethod
    @beartype
    def from_settings(
        cls,
        settings: MongoSettings,
        *,
        client: MongoClient[dict[str, Any]] | None = None,
    ) -> MongoOutboxStore:
        collection = resolve_collection(
            settings,
            collection_name=settings.outbox_collection,
            owner="MongoOutboxStore",
            client=client,
        )
        return cls.from_collection(
            collection,
            max_attempts=settings.outbox_max_attempts,
        )

    @beartype
    def ensure_indexes(self) -> None:
        self._collection.create_index(
            [("event_id", ASCENDING), ("handler_id", ASCENDING)],
            unique=True,
            name="outbox_event_handler_unique",
        )
        self._collection.create_index(
            [("status", ASCENDING), ("next_retry_at", ASCENDING)],
            name="outbox_pending_poll",
        )
        self._collection.create_index(
            [("status", ASCENDING), ("claimed_at", ASCENDING)],
            name="outbox_processing_lease",
        )

    @beartype
    def enqueue(
        self,
        *,
        event_id: str,
        handler_id: str,
        event_document: dict[str, Any],
        not_before: datetime | None = None,
    ) -> bool:
        document = {
            "entry_id": str(uuid.uuid4()),
            "event_id": event_id,
            "handler_id": handler_id,
            "event_document": event_document,
            "status": OUTBOX_STATUS_PENDING,
            "attempts": 0,
            "last_error": None,
            "next_retry_at": _utc_now(),
            "created_at": _utc_now(),
            "claimed_at": None,
            "claim_id": None,
            "not_before": not_before,
        }
        try:
            self._collection.insert_one(document)
            return True
        except DuplicateKeyError:
            return False

    @beartype
    def claim_pending(
        self,
        *,
        limit: int,
        handler_id: str | None = None,
        handler_ids: frozenset[str] | None = None,
    ) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        for _ in range(limit):
            now = _utc_now()
            claim_id = str(uuid.uuid4())
            query: dict[str, Any] = {
                "$or": [
                    {
                        "status": OUTBOX_STATUS_PENDING,
                        "next_retry_at": {"$lte": now},
                        "not_before": {"$not": {"$gt": now}},
                    },
                    {
                        "status": OUTBOX_STATUS_PROCESSING,
                        "claimed_at": {
                            "$lte": _stale_claim_cutoff(
                                now=now,
                                processing_lease_seconds=self.processing_lease_seconds,
                            ),
                        },
                    },
                ],
            }
            if handler_id is not None:
                query["handler_id"] = handler_id
            elif handler_ids is not None:
                query["handler_id"] = {"$in": list(handler_ids)}
            document = self._collection.find_one_and_update(
                query,
                {
                    "$set": {
                        "status": OUTBOX_STATUS_PROCESSING,
                        "claimed_at": now,
                        "claim_id": claim_id,
                    },
                },
                sort=[("created_at", ASCENDING)],
                return_document=True,
            )
            if document is None:
                break
            claimed.append(document)
        return claimed

    @beartype
    def reclaim_stuck_processing(self) -> int:
        now = _utc_now()
        cutoff = _stale_claim_cutoff(
            now=now,
            processing_lease_seconds=self.processing_lease_seconds,
        )
        result = self._collection.update_many(
            {
                "status": OUTBOX_STATUS_PROCESSING,
                "claimed_at": {"$lte": cutoff},
            },
            {
                "$set": {
                    "status": OUTBOX_STATUS_PENDING,
                    "next_retry_at": now,
                    "claimed_at": None,
                    "claim_id": None,
                },
            },
        )
        modified_count = getattr(result, "modified_count", 0)
        return int(modified_count) if isinstance(modified_count, int) else 0

    @beartype
    def mark_processed(self, entry_id: str, *, claim_id: str) -> bool:
        result = self._collection.update_one(
            {
                "entry_id": entry_id,
                "status": OUTBOX_STATUS_PROCESSING,
                "claim_id": claim_id,
            },
            {
                "$set": {
                    "status": OUTBOX_STATUS_PROCESSED,
                    "processed_at": _utc_now(),
                    "claimed_at": None,
                    "claim_id": None,
                },
            },
        )
        return _matched_count(result) == 1

    @beartype
    def mark_failed(
        self,
        entry_id: str,
        *,
        claim_id: str,
        error_message: str,
        permanent: bool = False,
        retry_delay: timedelta | None = None,
        max_attempts_override: int | None = None,
    ) -> bool:
        document = self._collection.find_one_and_update(
            {
                "entry_id": entry_id,
                "status": OUTBOX_STATUS_PROCESSING,
                "claim_id": claim_id,
            },
            {
                "$inc": {"attempts": 1},
                "$set": {
                    "last_error": error_message,
                },
            },
            return_document=True,
        )
        if document is None:
            return False

        if permanent:
            result = self._collection.update_one(
                {
                    "entry_id": entry_id,
                    "status": OUTBOX_STATUS_PROCESSING,
                    "claim_id": claim_id,
                },
                {
                    "$set": {
                        "status": OUTBOX_STATUS_FAILED,
                        "claimed_at": None,
                        "claim_id": None,
                    },
                },
            )
            return _matched_count(result) == 1

        attempts = int(document.get("attempts", 1))
        attempt_limit = (
            max_attempts_override if max_attempts_override is not None else self.max_attempts
        )
        retry = attempts < attempt_limit
        if retry:
            if retry_delay is not None:
                next_retry_at = _utc_now() + retry_delay
            else:
                delay_seconds = min(60.0, 2.0**attempts)
                next_retry_at = _utc_now() + timedelta(seconds=delay_seconds)
            result = self._collection.update_one(
                {
                    "entry_id": entry_id,
                    "status": OUTBOX_STATUS_PROCESSING,
                    "claim_id": claim_id,
                },
                {
                    "$set": {
                        "status": OUTBOX_STATUS_PENDING,
                        "next_retry_at": next_retry_at,
                        "claimed_at": None,
                        "claim_id": None,
                    },
                },
            )
            if _matched_count(result) != 1:
                return False
            return False

        result = self._collection.update_one(
            {
                "entry_id": entry_id,
                "status": OUTBOX_STATUS_PROCESSING,
                "claim_id": claim_id,
            },
            {
                "$set": {
                    "status": OUTBOX_STATUS_FAILED,
                    "claimed_at": None,
                    "claim_id": None,
                },
            },
        )
        return _matched_count(result) == 1

    @beartype
    def _document_to_failed_summary(
        self,
        document: dict[str, Any],
    ) -> FailedOutboxEntrySummary:
        created_at = document.get("created_at")
        if not isinstance(created_at, datetime):
            raise TypeError("created_at must be datetime")
        last_error = document.get("last_error")
        return FailedOutboxEntrySummary(
            entry_id=str(document["entry_id"]),
            event_id=str(document["event_id"]),
            handler_id=str(document["handler_id"]),
            attempts=int(document.get("attempts", 0)),
            last_error=str(last_error) if last_error is not None else None,
            created_at=created_at,
        )

    @beartype
    def list_failed(
        self,
        *,
        handler_id: str | None = None,
        limit: int = 20,
    ) -> tuple[FailedOutboxEntrySummary, ...]:
        query: dict[str, Any] = {"status": OUTBOX_STATUS_FAILED}
        if handler_id is not None:
            query["handler_id"] = handler_id
        cursor = self._collection.find(query).sort("created_at", -1).limit(limit)
        return tuple(self._document_to_failed_summary(doc) for doc in cursor)

    @beartype
    def count_failed(self, *, handler_id: str | None = None) -> int:
        query: dict[str, Any] = {"status": OUTBOX_STATUS_FAILED}
        if handler_id is not None:
            query["handler_id"] = handler_id
        return int(self._collection.count_documents(query))

    @beartype
    def get_failed_entry(self, entry_id: str) -> FailedOutboxEntrySummary | None:
        document = self._collection.find_one(
            {"entry_id": entry_id, "status": OUTBOX_STATUS_FAILED},
        )
        if document is None:
            return None
        return self._document_to_failed_summary(document)

    @beartype
    def requeue_failed(self, entry_id: str) -> bool:
        result = self._collection.update_one(
            {"entry_id": entry_id, "status": OUTBOX_STATUS_FAILED},
            {
                "$set": {
                    "status": OUTBOX_STATUS_PENDING,
                    "attempts": 0,
                    "last_error": None,
                    "next_retry_at": _utc_now(),
                    "claimed_at": None,
                    "claim_id": None,
                },
            },
        )
        return _matched_count(result) == 1

    @beartype
    def find_active_portion_event_id(self, technician_id: str) -> str | None:
        document = self._collection.find_one(
            {
                "status": {"$in": [OUTBOX_STATUS_PENDING, OUTBOX_STATUS_PROCESSING]},
                "handler_id": {"$in": sorted(SETTLEMENT_PORTION_HANDLER_IDS)},
                "event_id": {"$regex": f"^portion:{re.escape(technician_id)}:"},
            },
        )
        if document is None:
            return None
        return str(document["event_id"])
