from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from beartype import beartype

from src.application.machine_operations.ports import OutboxStore
from src.application.outbox import SETTLEMENT_PORTION_HANDLER_IDS
from src.application.outbox.ports import FailedOutboxEntrySummary

OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_PROCESSING = "processing"
OUTBOX_STATUS_PROCESSED = "processed"
OUTBOX_STATUS_FAILED = "failed"

DEFAULT_PROCESSING_LEASE_SECONDS = 300


@beartype
def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@beartype
def _stale_claim_cutoff(
    *,
    now: datetime,
    processing_lease_seconds: int,
) -> datetime:
    return now - timedelta(seconds=processing_lease_seconds)


@beartype
@dataclass(slots=True)
class InMemoryOutboxStore(OutboxStore):
    max_attempts: int = 5
    processing_lease_seconds: int = DEFAULT_PROCESSING_LEASE_SECONDS
    _entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    _dedupe_keys: set[tuple[str, str]] = field(default_factory=set)

    @beartype
    def enqueue(
        self,
        *,
        event_id: str,
        handler_id: str,
        event_document: dict[str, Any],
        not_before: datetime | None = None,
    ) -> bool:
        dedupe_key = (event_id, handler_id)
        if dedupe_key in self._dedupe_keys:
            return False

        entry_id = str(uuid.uuid4())
        self._entries[entry_id] = {
            "entry_id": entry_id,
            "event_id": event_id,
            "handler_id": handler_id,
            "event_document": event_document,
            "status": OUTBOX_STATUS_PENDING,
            "attempts": 0,
            "last_error": None,
            "next_retry_at": _utc_now(),
            "created_at": _utc_now(),
            "claim_id": None,
            "not_before": not_before,
        }
        self._dedupe_keys.add(dedupe_key)
        return True

    @beartype
    def claim_pending(
        self,
        *,
        limit: int,
        handler_id: str | None = None,
        handler_ids: frozenset[str] | None = None,
    ) -> list[dict[str, Any]]:
        now = _utc_now()
        pending = [
            entry
            for entry in self._entries.values()
            if entry["status"] == OUTBOX_STATUS_PENDING
            and entry["next_retry_at"] <= now
            and (entry.get("not_before") is None or entry["not_before"] <= now)
            and (handler_id is None or entry["handler_id"] == handler_id)
            and (handler_ids is None or entry["handler_id"] in handler_ids)
        ]
        pending.sort(key=lambda item: item["created_at"])
        claimed: list[dict[str, Any]] = []
        for entry in pending[:limit]:
            entry["status"] = OUTBOX_STATUS_PROCESSING
            entry["claimed_at"] = _utc_now()
            entry["claim_id"] = str(uuid.uuid4())
            claimed.append(dict(entry))
        return claimed

    @beartype
    def reclaim_stuck_processing(self) -> int:
        now = _utc_now()
        cutoff = _stale_claim_cutoff(
            now=now,
            processing_lease_seconds=self.processing_lease_seconds,
        )
        reclaimed = 0
        for entry in self._entries.values():
            if entry["status"] != OUTBOX_STATUS_PROCESSING:
                continue
            claimed_at = entry.get("claimed_at")
            if not isinstance(claimed_at, datetime) or claimed_at > cutoff:
                continue
            entry["status"] = OUTBOX_STATUS_PENDING
            entry["next_retry_at"] = now
            entry["claimed_at"] = None
            entry["claim_id"] = None
            reclaimed += 1
        return reclaimed

    @beartype
    def mark_processed(self, entry_id: str, *, claim_id: str) -> bool:
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        if entry["status"] != OUTBOX_STATUS_PROCESSING or entry.get("claim_id") != claim_id:
            return False
        entry["status"] = OUTBOX_STATUS_PROCESSED
        entry["processed_at"] = _utc_now()
        entry["claimed_at"] = None
        entry["claim_id"] = None
        return True

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
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        if entry["status"] != OUTBOX_STATUS_PROCESSING or entry.get("claim_id") != claim_id:
            return False

        entry["attempts"] = int(entry["attempts"]) + 1
        entry["last_error"] = error_message

        if permanent:
            entry["status"] = OUTBOX_STATUS_FAILED
            entry["claimed_at"] = None
            entry["claim_id"] = None
            return True

        attempt_limit = (
            max_attempts_override if max_attempts_override is not None else self.max_attempts
        )
        retry = int(entry["attempts"]) < attempt_limit

        if retry:
            if retry_delay is not None:
                entry["status"] = OUTBOX_STATUS_PENDING
                entry["next_retry_at"] = _utc_now() + retry_delay
            else:
                delay_seconds = min(60.0, 2.0 ** int(entry["attempts"]))
                entry["status"] = OUTBOX_STATUS_PENDING
                entry["next_retry_at"] = _utc_now() + timedelta(seconds=delay_seconds)
            entry["claimed_at"] = None
            entry["claim_id"] = None
            return False

        entry["status"] = OUTBOX_STATUS_FAILED
        entry["claimed_at"] = None
        entry["claim_id"] = None
        return True

    @beartype
    def find_active_portion_event_id(self, technician_id: str) -> str | None:
        prefix = f"portion:{technician_id}:"
        for entry in self._entries.values():
            if entry["status"] not in {OUTBOX_STATUS_PENDING, OUTBOX_STATUS_PROCESSING}:
                continue
            if entry["handler_id"] not in SETTLEMENT_PORTION_HANDLER_IDS:
                continue
            event_id = str(entry["event_id"])
            if event_id.startswith(prefix):
                return event_id
        return None

    @beartype
    def _to_failed_summary(self, entry: dict[str, Any]) -> FailedOutboxEntrySummary:
        created_at = entry["created_at"]
        if not isinstance(created_at, datetime):
            raise TypeError("created_at must be datetime")
        last_error = entry.get("last_error")
        return FailedOutboxEntrySummary(
            entry_id=str(entry["entry_id"]),
            event_id=str(entry["event_id"]),
            handler_id=str(entry["handler_id"]),
            attempts=int(entry["attempts"]),
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
        failed = [
            entry
            for entry in self._entries.values()
            if entry["status"] == OUTBOX_STATUS_FAILED
            and (handler_id is None or entry["handler_id"] == handler_id)
        ]
        failed.sort(key=lambda item: item["created_at"], reverse=True)
        return tuple(self._to_failed_summary(entry) for entry in failed[:limit])

    @beartype
    def count_failed(self, *, handler_id: str | None = None) -> int:
        return sum(
            1
            for entry in self._entries.values()
            if entry["status"] == OUTBOX_STATUS_FAILED
            and (handler_id is None or entry["handler_id"] == handler_id)
        )

    @beartype
    def get_failed_entry(self, entry_id: str) -> FailedOutboxEntrySummary | None:
        entry = self._entries.get(entry_id)
        if entry is None or entry["status"] != OUTBOX_STATUS_FAILED:
            return None
        return self._to_failed_summary(entry)

    @beartype
    def requeue_failed(self, entry_id: str) -> bool:
        entry = self._entries.get(entry_id)
        if entry is None or entry["status"] != OUTBOX_STATUS_FAILED:
            return False
        entry["status"] = OUTBOX_STATUS_PENDING
        entry["attempts"] = 0
        entry["last_error"] = None
        entry["next_retry_at"] = _utc_now()
        entry["claimed_at"] = None
        entry["claim_id"] = None
        return True
