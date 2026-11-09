from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from beartype import beartype

DraftKind = Literal["inventory", "exit"]

_MONEY_MAP_KEYS = frozenset(
    {
        "warehouse_delta_by_sku",
        "ledger_balance_before",
        "ledger_balance_session",
        "residual_by_sku",
        "cleared_by_sku",
        "delta_by_sku",
        "calculated_stock_by_sku",
        "actual_stock_by_sku",
        "previous_actual_by_sku",
        "supply_in_by_sku",
        "returns_by_sku",
        "loadings_by_sku",
    }
)


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationDraft:
    technician_id: str
    kind: DraftKind
    warehouse_inventory_id: str
    warehouse_inventory_moment: datetime
    plan: dict[str, Any]
    updated_at: datetime
    anchor_at: datetime | None = None

    @property
    def document_id(self) -> str:
        return f"{self.technician_id}:{self.kind}"


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def _money_map_to_storage(value: dict[str, Any]) -> dict[str, str]:
    return {str(sku): format(Decimal(str(amount)), "f") for sku, amount in value.items()}


@beartype
def _money_map_from_storage(value: dict[str, Any]) -> dict[str, Decimal]:
    return {str(sku): Decimal(str(amount)) for sku, amount in value.items()}


@beartype
def plan_to_storage(plan: dict[str, Any]) -> dict[str, Any]:
    converted = _convert_plan(plan, to_storage=True)
    if not isinstance(converted, dict):
        raise TypeError("plan_to_storage must return a dict")
    return converted


@beartype
def plan_from_storage(plan: dict[str, Any]) -> dict[str, Any]:
    converted = _convert_plan(plan, to_storage=False)
    if not isinstance(converted, dict):
        raise TypeError("plan_from_storage must return a dict")
    return converted


@beartype
def _convert_plan(value: Any, *, to_storage: bool) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if key_str in _MONEY_MAP_KEYS and isinstance(item, dict):
                result[key_str] = (
                    _money_map_to_storage(item) if to_storage else _money_map_from_storage(item)
                )
            else:
                result[key_str] = _convert_plan(item, to_storage=to_storage)
        return result
    if isinstance(value, list):
        return [_convert_plan(item, to_storage=to_storage) for item in value]
    if to_storage and isinstance(value, Decimal):
        return format(value, "f")
    return value


@beartype
def draft_to_document(draft: ReconciliationDraft) -> dict[str, Any]:
    return {
        "_id": draft.document_id,
        "technician_id": draft.technician_id,
        "kind": draft.kind,
        "warehouse_inventory_id": draft.warehouse_inventory_id,
        "warehouse_inventory_moment": _as_utc(draft.warehouse_inventory_moment),
        "plan": plan_to_storage(draft.plan),
        "updated_at": _as_utc(draft.updated_at),
        "anchor_at": _as_utc(draft.anchor_at) if draft.anchor_at is not None else None,
    }


@beartype
def draft_from_document(document: dict[str, Any]) -> ReconciliationDraft:
    kind = document["kind"]
    if kind not in ("inventory", "exit"):
        raise ValueError(f"Unknown draft kind: {kind!r}")
    anchor_at = document.get("anchor_at")
    return ReconciliationDraft(
        technician_id=str(document["technician_id"]),
        kind=kind,
        warehouse_inventory_id=str(document["warehouse_inventory_id"]),
        warehouse_inventory_moment=_as_utc(document["warehouse_inventory_moment"]),
        plan=plan_from_storage(dict(document["plan"])),
        updated_at=_as_utc(document["updated_at"]),
        anchor_at=_as_utc(anchor_at) if anchor_at is not None else None,
    )


@beartype
def serialize_inventory_plan(
    *,
    period_ids: tuple[str, ...],
    deferred_period_ids: tuple[str, ...],
    warehouse_delta_by_sku: dict[str, Decimal],
    ledger_balance_before: dict[str, Decimal],
    residual_by_sku: dict[str, Decimal],
    calculated_stock_by_sku: dict[str, Decimal],
    actual_stock_by_sku: dict[str, Decimal],
    previous_actual_by_sku: dict[str, Decimal],
    supply_in_by_sku: dict[str, Decimal],
    returns_by_sku: dict[str, Decimal],
    loadings_by_sku: dict[str, Decimal],
    transfer_refs: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    return {
        "mode": "inventory_delta",
        "period_ids": list(period_ids),
        "deferred_period_ids": list(deferred_period_ids),
        "warehouse_delta_by_sku": dict(warehouse_delta_by_sku),
        "ledger_balance_before": dict(ledger_balance_before),
        "residual_by_sku": dict(residual_by_sku),
        "calculated_stock_by_sku": dict(calculated_stock_by_sku),
        "actual_stock_by_sku": dict(actual_stock_by_sku),
        "previous_actual_by_sku": dict(previous_actual_by_sku),
        "supply_in_by_sku": dict(supply_in_by_sku),
        "returns_by_sku": dict(returns_by_sku),
        "loadings_by_sku": dict(loadings_by_sku),
        "transfer_refs": [
            {"external_document_id": doc_id, "content_hash": content_hash}
            for doc_id, content_hash in transfer_refs
        ],
    }


@beartype
def serialize_exit_plan(
    *,
    period_ids: tuple[str, ...],
    warehouse_delta_by_sku: dict[str, Decimal],
    ledger_balance_before: dict[str, Decimal],
    residual_by_sku: dict[str, Decimal],
    calculated_stock_by_sku: dict[str, Decimal],
    actual_stock_by_sku: dict[str, Decimal],
    previous_actual_by_sku: dict[str, Decimal],
    supply_in_by_sku: dict[str, Decimal],
    returns_by_sku: dict[str, Decimal],
    loadings_by_sku: dict[str, Decimal],
    transfer_refs: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    payload = serialize_inventory_plan(
        period_ids=period_ids,
        deferred_period_ids=(),
        warehouse_delta_by_sku=warehouse_delta_by_sku,
        ledger_balance_before=ledger_balance_before,
        residual_by_sku=residual_by_sku,
        calculated_stock_by_sku=calculated_stock_by_sku,
        actual_stock_by_sku=actual_stock_by_sku,
        previous_actual_by_sku=previous_actual_by_sku,
        supply_in_by_sku=supply_in_by_sku,
        returns_by_sku=returns_by_sku,
        loadings_by_sku=loadings_by_sku,
        transfer_refs=transfer_refs,
    )
    payload["mode"] = "exit_warehouse_closed"
    return payload


@beartype
def plan_money_map(plan: dict[str, Any], key: str) -> dict[str, Decimal]:
    raw = plan.get(key, {})
    if not isinstance(raw, dict):
        return {}
    return {str(sku): Decimal(str(amount)) for sku, amount in raw.items()}


@beartype
def plan_str_tuple(plan: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = plan.get(key, [])
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw)


@beartype
def plan_transfer_refs(plan: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    raw_refs = plan.get("transfer_refs", [])
    if not isinstance(raw_refs, list):
        return ()
    result: list[tuple[str, str]] = []
    for item in raw_refs:
        if not isinstance(item, dict):
            continue
        result.append((str(item["external_document_id"]), str(item["content_hash"])))
    return tuple(result)
