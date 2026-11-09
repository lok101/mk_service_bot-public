from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from beartype import beartype

from src.domain.ids import EventId
from src.domain.snack_loading.events import (
    CellKey,
    SnackInventoryAccepted,
    SnackLoadingApplied,
    SnackSaleDeducted,
    SnackStockAnomalyRecorded,
    SnackStockEvent,
)

_EVENT_TYPE_INVENTORY = "SnackInventoryAccepted"
_EVENT_TYPE_SALE = "SnackSaleDeducted"
_EVENT_TYPE_LOADING = "SnackLoadingApplied"
_EVENT_TYPE_ANOMALY = "SnackStockAnomalyRecorded"


@beartype
def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@beartype
def _cell_key_to_list(key: CellKey) -> list[object]:
    machine_code, logical_matrix_name, line_number = key
    return [machine_code, logical_matrix_name, line_number]


@beartype
def _cell_key_from_list(value: object) -> CellKey:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("cell key must be a 3-item list")
    machine_code, logical_matrix_name, line_number = value
    if (
        not isinstance(machine_code, str)
        or not isinstance(logical_matrix_name, str)
        or not isinstance(line_number, int)
        or isinstance(line_number, bool)
    ):
        raise ValueError("cell key has invalid shape")
    return (machine_code, logical_matrix_name, line_number)


@beartype
def _qty_pairs_to_list(
    pairs: tuple[tuple[CellKey, Decimal], ...],
) -> list[dict[str, object]]:
    return [{"key": _cell_key_to_list(key), "quantity": format(qty, "f")} for key, qty in pairs]


@beartype
def _qty_pairs_from_list(value: object) -> tuple[tuple[CellKey, Decimal], ...]:
    if not isinstance(value, list):
        raise ValueError("quantities must be a list")
    parsed: list[tuple[CellKey, Decimal]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("quantity item must be a dict")
        parsed.append((_cell_key_from_list(item["key"]), Decimal(str(item["quantity"]))))
    return tuple(parsed)


@beartype
def _product_pairs_to_list(
    pairs: tuple[tuple[CellKey, str], ...],
) -> list[dict[str, object]]:
    return [{"key": _cell_key_to_list(key), "product_code": product} for key, product in pairs]


@beartype
def _product_pairs_from_list(value: object) -> tuple[tuple[CellKey, str], ...]:
    if not isinstance(value, list):
        raise ValueError("product_by_key must be a list")
    parsed: list[tuple[CellKey, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("product item must be a dict")
        product = item["product_code"]
        if not isinstance(product, str):
            raise ValueError("product_code must be str")
        parsed.append((_cell_key_from_list(item["key"]), product))
    return tuple(parsed)


@beartype
def snack_stock_event_to_document(
    event: SnackStockEvent,
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
    if isinstance(event, SnackInventoryAccepted):
        base["payload"] = {
            "inventory_id": event.inventory_id,
            "as_of": _as_utc(event.as_of),
            "quantities": _qty_pairs_to_list(event.quantities),
            "product_by_key": _product_pairs_to_list(event.product_by_key),
        }
        return base
    if isinstance(event, SnackSaleDeducted):
        base["payload"] = {
            "source_id": event.source_id,
            "cell_key": _cell_key_to_list(event.cell_key),
            "product_code": event.product_code,
            "quantity": format(event.quantity, "f"),
        }
        return base
    if isinstance(event, SnackLoadingApplied):
        base["payload"] = {
            "run_id": event.run_id,
            "move_id": event.move_id,
            "increments": _qty_pairs_to_list(event.increments),
        }
        return base
    if isinstance(event, SnackStockAnomalyRecorded):
        base["payload"] = {
            "source_id": event.source_id,
            "cell_key": _cell_key_to_list(event.cell_key),
            "requested_quantity": format(event.requested_quantity, "f"),
            "available_quantity": format(event.available_quantity, "f"),
            "clamped_quantity": format(event.clamped_quantity, "f"),
        }
        return base
    raise TypeError(f"unsupported snack stock event: {type(event)!r}")


@beartype
def snack_stock_event_from_document(document: dict[str, Any]) -> SnackStockEvent:
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
        raise ValueError("snack stock event document has invalid shape")
    event_id = EventId(event_id_raw)
    occurred = _as_utc(occurred_at)
    if event_type == _EVENT_TYPE_INVENTORY:
        as_of = payload["as_of"]
        inventory_id = payload["inventory_id"]
        if not isinstance(as_of, datetime) or not isinstance(inventory_id, str):
            raise ValueError("inventory payload invalid")
        return SnackInventoryAccepted(
            event_id=event_id,
            machine_code=machine_code,
            inventory_id=inventory_id,
            as_of=_as_utc(as_of),
            quantities=_qty_pairs_from_list(payload["quantities"]),
            product_by_key=_product_pairs_from_list(payload["product_by_key"]),
            occurred_at=occurred,
        )
    if event_type == _EVENT_TYPE_SALE:
        source_id = payload["source_id"]
        product_code = payload["product_code"]
        if not isinstance(source_id, str) or not isinstance(product_code, str):
            raise ValueError("sale payload invalid")
        return SnackSaleDeducted(
            event_id=event_id,
            machine_code=machine_code,
            source_id=source_id,
            cell_key=_cell_key_from_list(payload["cell_key"]),
            product_code=product_code,
            quantity=Decimal(str(payload["quantity"])),
            occurred_at=occurred,
        )
    if event_type == _EVENT_TYPE_LOADING:
        run_id = payload["run_id"]
        move_id = payload["move_id"]
        if not isinstance(run_id, str) or not isinstance(move_id, str):
            raise ValueError("loading payload invalid")
        return SnackLoadingApplied(
            event_id=event_id,
            machine_code=machine_code,
            run_id=run_id,
            move_id=move_id,
            increments=_qty_pairs_from_list(payload["increments"]),
            occurred_at=occurred,
        )
    if event_type == _EVENT_TYPE_ANOMALY:
        source_id = payload["source_id"]
        if not isinstance(source_id, str):
            raise ValueError("anomaly payload invalid")
        return SnackStockAnomalyRecorded(
            event_id=event_id,
            machine_code=machine_code,
            source_id=source_id,
            cell_key=_cell_key_from_list(payload["cell_key"]),
            requested_quantity=Decimal(str(payload["requested_quantity"])),
            available_quantity=Decimal(str(payload["available_quantity"])),
            clamped_quantity=Decimal(str(payload["clamped_quantity"])),
            occurred_at=occurred,
        )
    raise ValueError(f"unknown snack stock event_type: {event_type}")
