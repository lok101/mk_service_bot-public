from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import BatchId, EventId, MachineId, RevisionId, TechnicianId
from src.domain.machine_operations.events import (
    DomainEvent,
    LoadingSubmitted,
    MaintenanceCompleted,
    PhotosSubmitted,
    RevisionCompleted,
)
from src.domain.models import RevisionSource
from src.infrastructure.mongodb.contracts import (
    MACHINE_OPERATIONS_AGGREGATE_TYPE,
    MongoEventDocument,
    MongoPayload,
)

_REVISION_COMPLETED = RevisionCompleted.__name__
_LOADING_SUBMITTED = LoadingSubmitted.__name__
_MAINTENANCE_COMPLETED = MaintenanceCompleted.__name__
MAINTENANCE_COMPLETED_EVENT_TYPE = _MAINTENANCE_COMPLETED
_PHOTOS_SUBMITTED = PhotosSubmitted.__name__
PHOTOS_SUBMITTED_EVENT_TYPE = _PHOTOS_SUBMITTED


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
def machine_id_from_event(event: DomainEvent) -> MachineId:
    machine_id = getattr(event, "machine_id", None)
    if not isinstance(machine_id, MachineId):
        raise TypeError(f"Event {type(event)!r} has no machine_id")
    return machine_id


@beartype
def event_to_document(event: DomainEvent, *, aggregate_version: int) -> MongoEventDocument:
    machine_id = machine_id_from_event(event)
    if isinstance(event, RevisionCompleted):
        payload: MongoPayload = {
            "revision_id": event.revision_id.value,
            "technician_id": event.technician_id.value,
            "machine_id": event.machine_id.value,
            "completed_at": event.completed_at,
            "source": event.source.value,
            "form_id": event.form_id,
            "form_token": event.form_token,
        }
        if event.responsibility_expires_at is not None:
            payload["responsibility_expires_at"] = event.responsibility_expires_at
        event_type = _REVISION_COMPLETED
    elif isinstance(event, LoadingSubmitted):
        payload = {
            "technician_id": event.technician_id.value,
            "machine_id": event.machine_id.value,
            "submitted_at": event.submitted_at,
            "form_id": event.form_id,
            "form_token": event.form_token,
        }
        event_type = _LOADING_SUBMITTED
    elif isinstance(event, MaintenanceCompleted):
        payload = {
            "technician_id": event.technician_id.value,
            "machine_id": event.machine_id.value,
            "completed_at": event.completed_at,
        }
        event_type = _MAINTENANCE_COMPLETED
    elif isinstance(event, PhotosSubmitted):
        payload = {
            "batch_id": event.batch_id.value,
            "technician_id": event.technician_id.value,
            "machine_id": event.machine_id.value,
            "photo_count": event.photo_count,
            "submitted_at": event.submitted_at,
            "purpose": event.purpose,
        }
        if event.maintenance_completed_at is not None:
            payload["maintenance_completed_at"] = event.maintenance_completed_at
        event_type = _PHOTOS_SUBMITTED
    else:
        raise TypeError(f"Unsupported domain event type: {type(event)!r}")

    return MongoEventDocument(
        event_id=event.event_id.value,
        event_type=event_type,
        aggregate_id=machine_id.value,
        aggregate_type=MACHINE_OPERATIONS_AGGREGATE_TYPE,
        aggregate_version=aggregate_version,
        occurred_at=event.occurred_at,
        payload=payload,
        metadata={},
    )


@beartype
def document_to_bson(document: MongoEventDocument) -> dict[str, Any]:
    return {
        "event_id": document.event_id,
        "event_type": document.event_type,
        "aggregate_id": document.aggregate_id,
        "aggregate_type": document.aggregate_type,
        "aggregate_version": document.aggregate_version,
        "occurred_at": document.occurred_at,
        "payload": document.payload,
        "metadata": document.metadata,
    }


@beartype
def document_from_event(event: DomainEvent, *, aggregate_version: int) -> dict[str, Any]:
    return document_to_bson(event_to_document(event, aggregate_version=aggregate_version))


@beartype
def _event_id_from_document(document: dict[str, Any]) -> EventId:
    event_id = document.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise ValueError("Stored event document is missing event_id")
    return EventId(event_id)


@beartype
def event_from_bson(document: dict[str, Any]) -> DomainEvent:
    event_type = document.get("event_type")
    payload = document.get("payload")
    if not isinstance(event_type, str) or not isinstance(payload, dict):
        raise ValueError("Stored event document is missing event_type or payload")

    event_id = _event_id_from_document(document)
    occurred_at_raw = document.get("occurred_at")
    if not isinstance(occurred_at_raw, datetime):
        raise ValueError("Stored event document is missing occurred_at")
    occurred_at = _as_utc(occurred_at_raw)

    if event_type == _REVISION_COMPLETED:
        source_value = _require_str(payload, "source")
        responsibility_expires_at_raw = payload.get("responsibility_expires_at")
        responsibility_expires_at = (
            _require_datetime(payload, "responsibility_expires_at")
            if responsibility_expires_at_raw is not None
            else None
        )
        return RevisionCompleted(
            event_id=event_id,
            revision_id=RevisionId(_require_str(payload, "revision_id")),
            technician_id=TechnicianId(_require_str(payload, "technician_id")),
            machine_id=MachineId(_require_str(payload, "machine_id")),
            completed_at=_require_datetime(payload, "completed_at"),
            occurred_at=occurred_at,
            source=RevisionSource(source_value),
            form_id=_require_str(payload, "form_id"),
            form_token=_require_str(payload, "form_token"),
            responsibility_expires_at=responsibility_expires_at,
        )

    if event_type == "PreLoadingSubmitted":
        raise ValueError(
            f"Unsupported stored event_type: {event_type!r} "
            "(PreLoadingSubmitted removed after R2; migrate machine_events first)"
        )

    if event_type == _LOADING_SUBMITTED:
        return LoadingSubmitted(
            event_id=event_id,
            technician_id=TechnicianId(_require_str(payload, "technician_id")),
            machine_id=MachineId(_require_str(payload, "machine_id")),
            submitted_at=_require_datetime(payload, "submitted_at"),
            occurred_at=occurred_at,
            form_id=_require_str(payload, "form_id"),
            form_token=_require_str(payload, "form_token"),
        )

    if event_type == _MAINTENANCE_COMPLETED:
        return MaintenanceCompleted(
            event_id=event_id,
            technician_id=TechnicianId(_require_str(payload, "technician_id")),
            machine_id=MachineId(_require_str(payload, "machine_id")),
            completed_at=_require_datetime(payload, "completed_at"),
            occurred_at=occurred_at,
        )

    if event_type == _PHOTOS_SUBMITTED:
        purpose = _require_str(payload, "purpose")
        if purpose != "loading":
            raise ValueError(f"Unsupported photo purpose: {purpose!r}")
        photo_count = payload.get("photo_count")
        if not isinstance(photo_count, int) or photo_count < 1:
            raise ValueError("Event payload field 'photo_count' must be a positive int")
        maintenance_completed_at_raw = payload.get("maintenance_completed_at")
        maintenance_completed_at = (
            _require_datetime(payload, "maintenance_completed_at")
            if maintenance_completed_at_raw is not None
            else None
        )
        return PhotosSubmitted(
            event_id=event_id,
            batch_id=BatchId(_require_str(payload, "batch_id")),
            technician_id=TechnicianId(_require_str(payload, "technician_id")),
            machine_id=MachineId(_require_str(payload, "machine_id")),
            photo_count=photo_count,
            submitted_at=_require_datetime(payload, "submitted_at"),
            occurred_at=occurred_at,
            purpose="loading",
            maintenance_completed_at=maintenance_completed_at,
        )

    raise ValueError(f"Unsupported stored event_type: {event_type!r}")
