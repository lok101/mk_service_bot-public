from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from beartype import beartype

from src.domain.ids import EventId
from src.domain.micromarket_loading.events import (
    MicromarketInventoryAccepted,
    MicromarketLoadingApplied,
    MicromarketSaleDeducted,
    MicromarketStockAnomalyRecorded,
    MicromarketStockEvent,
)

_EVENT_TYPE_INVENTORY = "MicromarketInventoryAccepted"
_EVENT_TYPE_SALE = "MicromarketSaleDeducted"
_EVENT_TYPE_LOADING = "MicromarketLoadingApplied"
_EVENT_TYPE_ANOMALY = "MicromarketStockAnomalyRecorded"


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _qty_pairs_to_list(
    pairs: tuple[tuple[str, Decimal], ...],
) -> list[dict[str, object]]:
    return [{"product_code": code, "quantity": format(qty, "f")} for code, qty in pairs]


@beartype
def _qty_pairs_from_list(value: object) -> tuple[tuple[str, Decimal], ...]:
    if not isinstance(value, list):
        raise ValueError("quantities must be a list")
    parsed: list[tuple[str, Decimal]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("quantity item must be a dict")
        product_code = item["product_code"]
        if not isinstance(product_code, str):
            raise ValueError("product_code must be str")
        parsed.append((product_code, Decimal(str(item["quantity"]))))
    return tuple(parsed)


@beartype
def micromarket_stock_event_to_document(
    event: MicromarketStockEvent,
    *,
    stream_version: int,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_id": event.event_id.value,
        "machine_code": event.machine_code,
        "stream_version": stream_version,
        "occurred_at": _as_utc(event.occurred_at),
        "event_type": event.__class__.__name__,
    }
    if isinstance(event, MicromarketInventoryAccepted):
        base["payload"] = {
            "inventory_id": event.inventory_id,
            "as_of": _as_utc(event.as_of),
            "quantities": _qty_pairs_to_list(event.quantities),
            "partial": event.partial,
        }
        return base
    if isinstance(event, MicromarketSaleDeducted):
        base["payload"] = {
            "sale_source_id": event.sale_source_id,
            "product_code": event.product_code,
            "qty": format(event.qty, "f"),
        }
        return base
    if isinstance(event, MicromarketLoadingApplied):
        base["payload"] = {
            "loading_run_id": event.loading_run_id,
            "lines": _qty_pairs_to_list(event.lines),
        }
        return base
    if isinstance(event, MicromarketStockAnomalyRecorded):
        base["payload"] = {
            "kind": event.kind,
            "product_code": event.product_code,
            "detail": event.detail,
            "sale_source_id": event.sale_source_id,
            "requested_qty": format(event.requested_qty, "f"),
            "available_qty": format(event.available_qty, "f"),
            "clamped_qty": format(event.clamped_qty, "f"),
        }
        return base
    raise TypeError(f"unsupported micromarket stock event: {type(event)!r}")


@beartype
def micromarket_stock_event_from_document(document: dict[str, Any]) -> MicromarketStockEvent:
    event_id_raw = document.get("event_id")
    machine_code = document.get("machine_code")
    occurred_at = document.get("occurred_at")
    event_type = document.get("event_type")
    payload = document.get("payload")
    if (
        not isinstance(event_id_raw, str)
        or not isinstance(machine_code, str)
        or not isinstance(occurred_at, datetime)
        or not isinstance(event_type, str)
        or not isinstance(payload, dict)
    ):
        raise ValueError("micromarket stock event document has invalid shape")
    event_id = EventId(event_id_raw)
    occurred = _as_utc(occurred_at)
    if event_type == _EVENT_TYPE_INVENTORY:
        as_of = payload["as_of"]
        inventory_id = payload["inventory_id"]
        if not isinstance(as_of, datetime) or not isinstance(inventory_id, str):
            raise ValueError("inventory payload invalid")
        partial = bool(payload["partial"]) if "partial" in payload else False
        return MicromarketInventoryAccepted(
            event_id=event_id,
            machine_code=machine_code,
            inventory_id=inventory_id,
            as_of=_as_utc(as_of),
            quantities=_qty_pairs_from_list(payload["quantities"]),
            occurred_at=occurred,
            partial=partial,
        )
    if event_type == _EVENT_TYPE_SALE:
        sale_source_id = payload["sale_source_id"]
        product_code = payload["product_code"]
        if not isinstance(sale_source_id, str) or not isinstance(product_code, str):
            raise ValueError("sale payload invalid")
        return MicromarketSaleDeducted(
            event_id=event_id,
            machine_code=machine_code,
            sale_source_id=sale_source_id,
            product_code=product_code,
            qty=Decimal(str(payload["qty"])),
            occurred_at=occurred,
        )
    if event_type == _EVENT_TYPE_LOADING:
        loading_run_id = payload["loading_run_id"]
        if not isinstance(loading_run_id, str):
            raise ValueError("loading payload invalid")
        return MicromarketLoadingApplied(
            event_id=event_id,
            machine_code=machine_code,
            loading_run_id=loading_run_id,
            lines=_qty_pairs_from_list(payload["lines"]),
            occurred_at=occurred,
        )
    if event_type == _EVENT_TYPE_ANOMALY:
        kind = payload["kind"]
        product_code = payload["product_code"]
        detail = payload["detail"]
        sale_source_id = payload["sale_source_id"]
        if (
            not isinstance(kind, str)
            or not isinstance(product_code, str)
            or not isinstance(detail, str)
            or not isinstance(sale_source_id, str)
        ):
            raise ValueError("anomaly payload invalid")
        return MicromarketStockAnomalyRecorded(
            event_id=event_id,
            machine_code=machine_code,
            kind=kind,
            product_code=product_code,
            detail=detail,
            sale_source_id=sale_source_id,
            requested_qty=Decimal(str(payload["requested_qty"])),
            available_qty=Decimal(str(payload["available_qty"])),
            clamped_qty=Decimal(str(payload["clamped_qty"])),
            occurred_at=occurred,
        )
    raise ValueError(f"unknown micromarket stock event_type: {event_type}")
