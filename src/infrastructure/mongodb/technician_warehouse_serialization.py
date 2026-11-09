from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from beartype import beartype

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseExitClosed,
    TechnicianWarehouseInventoryCounted,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferFinalized,
    TechnicianWarehouseTransferObserved,
    TechnicianWarehouseTransferVoided,
    WarehouseEvent,
)
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection

TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE = "TechnicianWarehouse"


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def _line_to_dict(line: TechnicianWarehouseLine) -> dict[str, str]:
    return {
        "sku": line.sku,
        "quantity_base": format(line.quantity_base, "f"),
    }


@beartype
def _line_from_dict(value: object) -> TechnicianWarehouseLine:
    if not isinstance(value, dict):
        raise ValueError("warehouse line must be a dict")
    return TechnicianWarehouseLine(
        sku=str(value["sku"]),
        quantity_base=Decimal(str(value["quantity_base"])),
    )


@beartype
def _inventory_lines_to_dict(
    lines: tuple[tuple[str, Decimal], ...],
) -> list[dict[str, str]]:
    return [{"sku": sku, "quantity": format(quantity, "f")} for sku, quantity in lines]


@beartype
def _inventory_lines_from(value: object) -> tuple[tuple[str, Decimal], ...]:
    if not isinstance(value, list):
        raise ValueError("inventory lines must be a list")
    parsed: list[tuple[str, Decimal]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("inventory line must be a dict")
        parsed.append((str(item["sku"]), Decimal(str(item["quantity"]))))
    return tuple(parsed)


@beartype
def warehouse_event_to_document(
    event: WarehouseEvent,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    payload = _payload_for(event)
    return {
        "event_id": event.event_id.value,
        "event_type": event.__class__.__name__,
        "aggregate_id": event.technician_id.value,
        "aggregate_type": TECHNICIAN_WAREHOUSE_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": payload,
    }


@beartype
def _payload_for(event: WarehouseEvent) -> dict[str, Any]:
    if isinstance(event, TechnicianWarehouseTransferObserved):
        return {
            "external_document_id": event.external_document_id,
            "moment": _as_utc(event.moment),
            "updated_at": _as_utc(event.updated_at),
            "observed_at": _as_utc(event.observed_at),
            "content_hash": event.content_hash,
            "direction": event.direction.value,
            "lines": [_line_to_dict(line) for line in event.lines],
        }
    if isinstance(event, TechnicianWarehouseTransferVoided):
        return {
            "external_document_id": event.external_document_id,
            "previous_content_hash": event.previous_content_hash,
            "observed_at": _as_utc(event.observed_at),
        }
    if isinstance(event, TechnicianWarehouseLoadingObserved):
        return {
            "source_event_id": event.source_event_id,
            "machine_id": event.machine_id.value,
            "submitted_at": _as_utc(event.submitted_at),
            "lines": [_line_to_dict(line) for line in event.lines],
        }
    if isinstance(event, TechnicianWarehouseInventoryCounted):
        return {
            "inventory_id": event.inventory_id,
            "form_token": event.form_token,
            "counted_at": _as_utc(event.counted_at),
            "lines": _inventory_lines_to_dict(event.lines),
            "baseline": event.baseline,
        }
    if isinstance(event, TechnicianWarehouseTransferFinalized):
        return {
            "session_id": event.session_id,
            "external_document_ids": list(event.external_document_ids),
            "finalized_at": _as_utc(event.finalized_at),
        }
    if isinstance(event, TechnicianWarehouseExitClosed):
        return {
            "closed_at": _as_utc(event.closed_at),
            "return_external_document_id": event.return_external_document_id,
            "return_content_hash": event.return_content_hash,
        }
    raise ValueError(f"Unknown technician warehouse event type: {event.__class__.__name__}")


@beartype
def warehouse_event_from_document(document: dict[str, Any]) -> WarehouseEvent:
    event_type = document["event_type"]
    payload = document["payload"]
    event_id = EventId(document["event_id"])
    technician_id = TechnicianId(document["aggregate_id"])
    occurred_at = _as_utc(document["occurred_at"])

    if event_type == TechnicianWarehouseTransferObserved.__name__:
        return TechnicianWarehouseTransferObserved(
            event_id=event_id,
            technician_id=technician_id,
            occurred_at=occurred_at,
            external_document_id=payload["external_document_id"],
            moment=_as_utc(payload["moment"]),
            updated_at=_as_utc(payload["updated_at"]),
            observed_at=_as_utc(payload["observed_at"]),
            content_hash=payload["content_hash"],
            direction=TransferDirection(payload["direction"]),
            lines=tuple(_line_from_dict(line) for line in payload["lines"]),
        )
    if event_type == TechnicianWarehouseTransferVoided.__name__:
        return TechnicianWarehouseTransferVoided(
            event_id=event_id,
            technician_id=technician_id,
            occurred_at=occurred_at,
            external_document_id=payload["external_document_id"],
            previous_content_hash=payload["previous_content_hash"],
            observed_at=_as_utc(payload["observed_at"]),
        )
    if event_type == TechnicianWarehouseLoadingObserved.__name__:
        return TechnicianWarehouseLoadingObserved(
            event_id=event_id,
            technician_id=technician_id,
            occurred_at=occurred_at,
            source_event_id=payload["source_event_id"],
            machine_id=MachineId(payload["machine_id"]),
            submitted_at=_as_utc(payload["submitted_at"]),
            lines=tuple(_line_from_dict(line) for line in payload["lines"]),
        )
    if event_type == TechnicianWarehouseInventoryCounted.__name__:
        return TechnicianWarehouseInventoryCounted(
            event_id=event_id,
            technician_id=technician_id,
            occurred_at=occurred_at,
            inventory_id=payload["inventory_id"],
            form_token=payload["form_token"],
            counted_at=_as_utc(payload["counted_at"]),
            lines=_inventory_lines_from(payload["lines"]),
            baseline=bool(payload["baseline"]),
        )
    if event_type == TechnicianWarehouseTransferFinalized.__name__:
        return TechnicianWarehouseTransferFinalized(
            event_id=event_id,
            technician_id=technician_id,
            occurred_at=occurred_at,
            session_id=payload["session_id"],
            external_document_ids=tuple(payload["external_document_ids"]),
            finalized_at=_as_utc(payload["finalized_at"]),
        )
    if event_type == TechnicianWarehouseExitClosed.__name__:
        return TechnicianWarehouseExitClosed(
            event_id=event_id,
            technician_id=technician_id,
            occurred_at=occurred_at,
            closed_at=_as_utc(payload["closed_at"]),
            return_external_document_id=payload["return_external_document_id"],
            return_content_hash=payload["return_content_hash"],
        )
    raise ValueError(f"Unknown technician warehouse event type: {event_type}")
