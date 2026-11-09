from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import BatchId, EventId, FindingId, MachineId, TechnicianId
from src.domain.technician_accountability.events import (
    AccountabilityEvent,
    PhotoDuplicateReviewCompleted,
    PhotoDuplicateSuspected,
)
from src.infrastructure.mongodb.contracts import MongoPayload

_PHOTO_DUPLICATE_SUSPECTED = PhotoDuplicateSuspected.__name__
_PHOTO_DUPLICATE_REVIEW_COMPLETED = PhotoDuplicateReviewCompleted.__name__
TECHNICIAN_ACCOUNTABILITY_AGGREGATE_TYPE = "TechnicianAccountability"


@beartype
def _require_str(payload: MongoPayload, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Event payload field {key!r} must be a non-empty string")
    return value


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _require_datetime(payload: MongoPayload, key: str) -> datetime:
    value = payload.get(key)
    if not isinstance(value, datetime):
        raise ValueError(f"Event payload field {key!r} must be a datetime")
    return _as_utc(value)


@beartype
def technician_id_from_event(event: AccountabilityEvent) -> TechnicianId:
    technician_id = getattr(event, "technician_id", None)
    if not isinstance(technician_id, TechnicianId):
        raise TypeError(f"Event {type(event)!r} has no technician_id")
    return technician_id


@beartype
def accountability_event_to_document(
    event: AccountabilityEvent,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    technician_id = technician_id_from_event(event)
    if isinstance(event, PhotoDuplicateSuspected):
        payload: MongoPayload = {
            "finding_id": event.finding_id.value,
            "technician_id": event.technician_id.value,
            "new_batch_id": event.new_batch_id.value,
            "matched_batch_id": event.matched_batch_id.value,
            "new_machine_id": event.new_machine_id.value,
            "matched_machine_id": event.matched_machine_id.value,
            "content_hash": event.content_hash,
            "photo_index": event.photo_index,
            "detected_at": event.detected_at,
        }
        event_type = _PHOTO_DUPLICATE_SUSPECTED
    elif isinstance(event, PhotoDuplicateReviewCompleted):
        payload = {
            "finding_id": event.finding_id.value,
            "technician_id": event.technician_id.value,
            "verdict": event.verdict,
            "reviewed_at": event.reviewed_at,
            "reviewer_note": event.reviewer_note,
        }
        event_type = _PHOTO_DUPLICATE_REVIEW_COMPLETED
    else:
        raise TypeError(f"Unsupported accountability event type: {type(event)!r}")

    return {
        "event_id": event.event_id.value,
        "event_type": event_type,
        "aggregate_id": technician_id.value,
        "aggregate_type": TECHNICIAN_ACCOUNTABILITY_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": event.occurred_at,
        "payload": payload,
    }


@beartype
def accountability_event_from_document(document: dict[str, Any]) -> AccountabilityEvent:
    event_id_raw = document.get("event_id")
    event_type = document.get("event_type")
    payload = document.get("payload")
    occurred_at = document.get("occurred_at")
    if (
        not isinstance(event_id_raw, str)
        or not isinstance(event_type, str)
        or not isinstance(payload, dict)
        or not isinstance(occurred_at, datetime)
    ):
        raise ValueError("Accountability event document has invalid shape")

    event_id = EventId(event_id_raw)
    occurred_at_utc = _as_utc(occurred_at)

    if event_type == _PHOTO_DUPLICATE_SUSPECTED:
        return PhotoDuplicateSuspected(
            event_id=event_id,
            finding_id=FindingId(_require_str(payload, "finding_id")),
            technician_id=TechnicianId(_require_str(payload, "technician_id")),
            new_batch_id=BatchId(_require_str(payload, "new_batch_id")),
            matched_batch_id=BatchId(_require_str(payload, "matched_batch_id")),
            new_machine_id=MachineId(_require_str(payload, "new_machine_id")),
            matched_machine_id=MachineId(_require_str(payload, "matched_machine_id")),
            content_hash=_require_str(payload, "content_hash"),
            photo_index=int(payload.get("photo_index", -1)),
            detected_at=_require_datetime(payload, "detected_at"),
            occurred_at=occurred_at_utc,
        )
    if event_type == _PHOTO_DUPLICATE_REVIEW_COMPLETED:
        verdict = _require_str(payload, "verdict")
        if verdict not in {"confirmed", "false_positive"}:
            raise ValueError("verdict must be confirmed or false_positive")
        reviewer_note = payload.get("reviewer_note", "")
        return PhotoDuplicateReviewCompleted(
            event_id=event_id,
            finding_id=FindingId(_require_str(payload, "finding_id")),
            technician_id=TechnicianId(_require_str(payload, "technician_id")),
            verdict=verdict,  # type: ignore[arg-type]
            reviewed_at=_require_datetime(payload, "reviewed_at"),
            occurred_at=occurred_at_utc,
            reviewer_note=reviewer_note if isinstance(reviewer_note, str) else "",
        )
    raise ValueError(f"Unknown accountability event type: {event_type!r}")
