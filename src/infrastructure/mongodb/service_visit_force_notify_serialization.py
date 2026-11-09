from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from beartype import beartype

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.service_visits import ServiceVisitForceNotifyRequested

SERVICE_VISIT_FORCE_NOTIFY_AGGREGATE_TYPE = "service_visit_force_notify"


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def service_visit_force_notify_event_to_document(
    event: ServiceVisitForceNotifyRequested,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    return {
        "event_id": event.event_id.value,
        "event_type": type(event).__name__,
        "aggregate_id": event.visit_id,
        "aggregate_type": SERVICE_VISIT_FORCE_NOTIFY_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": {
            "visit_id": event.visit_id,
            "machine_id": event.machine_id.value,
            "technician_id": event.technician_id.value,
            "technician_display": event.technician_display,
            "telegram_user_id": event.telegram_user_id,
            "outcome": event.outcome,
            "incident_source": event.incident_source,
            "machine_display": event.machine_display,
            "location_display": event.location_display,
        },
    }


@beartype
def service_visit_force_notify_event_from_document(
    document: dict[str, Any],
) -> ServiceVisitForceNotifyRequested:
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise ValueError("service visit force notify payload must be a dict")
    telegram_raw = payload.get("telegram_user_id")
    telegram_user_id = int(telegram_raw) if telegram_raw is not None else None
    return ServiceVisitForceNotifyRequested(
        event_id=EventId(str(document["event_id"])),
        visit_id=str(payload["visit_id"]),
        machine_id=MachineId(str(payload["machine_id"])),
        technician_id=TechnicianId(str(payload["technician_id"])),
        technician_display=str(payload["technician_display"]),
        telegram_user_id=telegram_user_id,
        outcome=str(payload["outcome"]),
        incident_source=(
            str(payload["incident_source"]) if payload.get("incident_source") is not None else None
        ),
        machine_display=(
            str(payload["machine_display"]) if payload.get("machine_display") is not None else None
        ),
        location_display=(
            str(payload["location_display"])
            if payload.get("location_display") is not None
            else None
        ),
        occurred_at=_as_utc(document["occurred_at"]),
    )
