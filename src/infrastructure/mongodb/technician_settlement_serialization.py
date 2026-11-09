from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from beartype import beartype

from src.domain.ids import (
    AccountabilityId,
    EventId,
    MachineId,
    ReconciliationSessionId,
    TechnicianId,
)
from src.domain.technician_settlement.events import (
    PeriodAccountabilityRecorded,
    SettlementEvent,
    TechnicianLedgerClearedByReconciliation,
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
    WarehouseTransferRef,
)

TECHNICIAN_SETTLEMENT_AGGREGATE_TYPE = "TechnicianSettlement"


@beartype
def _money_map(value: dict[str, Decimal]) -> dict[str, str]:
    return {sku: format(amount, "f") for sku, amount in value.items()}


@beartype
def _money_map_from(value: object) -> dict[str, Decimal]:
    if not isinstance(value, dict):
        raise ValueError("money map must be a dict")
    return {str(sku): Decimal(str(amount)) for sku, amount in value.items()}


@beartype
def _transfer_refs_to_payload(
    refs: tuple[WarehouseTransferRef, ...],
) -> list[dict[str, str]]:
    return [
        {
            "external_document_id": ref.external_document_id,
            "content_hash": ref.content_hash,
        }
        for ref in refs
    ]


@beartype
def _transfer_refs_from_payload(value: object) -> tuple[WarehouseTransferRef, ...]:
    if not isinstance(value, list):
        raise ValueError("warehouse_transfer_refs must be a list")
    refs: list[WarehouseTransferRef] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("warehouse_transfer_refs item must be a dict")
        refs.append(
            WarehouseTransferRef(
                external_document_id=str(item["external_document_id"]),
                content_hash=str(item["content_hash"]),
            ),
        )
    return tuple(refs)


@beartype
def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


@beartype
def technician_id_from_event(event: SettlementEvent) -> TechnicianId:
    return event.technician_id


@beartype
def settlement_event_to_document(
    event: SettlementEvent,
    *,
    aggregate_version: int,
) -> dict[str, Any]:
    payload = _payload_for(event)
    return {
        "event_id": event.event_id.value,
        "event_type": event.__class__.__name__,
        "aggregate_id": event.technician_id.value,
        "aggregate_type": TECHNICIAN_SETTLEMENT_AGGREGATE_TYPE,
        "aggregate_version": aggregate_version,
        "occurred_at": _as_utc(event.occurred_at),
        "payload": payload,
    }


@beartype
def _payload_for(event: SettlementEvent) -> dict[str, Any]:
    if isinstance(event, PeriodAccountabilityRecorded):
        return {
            "accountability_id": event.accountability_id.value,
            "period_id": event.period_id,
            "machine_id": event.machine_id.value,
            "delta_by_sku": _money_map(event.delta_by_sku),
            "closed_at": _as_utc(event.closed_at),
        }
    if isinstance(event, TechnicianReconciliationSessionCompleted):
        return {
            "session_id": event.session_id.value,
            "mode": event.mode,
            "anchor_at": _as_utc(event.anchor_at),
            "period_ids": list(event.period_ids),
            "deferred_period_ids": list(event.deferred_period_ids),
            "warehouse_inventory_id": event.warehouse_inventory_id,
            "warehouse_inventory_moment": (
                _as_utc(event.warehouse_inventory_moment)
                if event.warehouse_inventory_moment is not None
                else None
            ),
            "warehouse_delta_by_sku": _money_map(event.warehouse_delta_by_sku),
            "warehouse_source": event.warehouse_source,
            "warehouse_transfer_refs": _transfer_refs_to_payload(event.warehouse_transfer_refs),
            "ledger_balance_before": _money_map(event.ledger_balance_before),
            "residual_by_sku": _money_map(event.residual_by_sku),
            "finalized_at": _as_utc(event.finalized_at),
            "executed_at": _as_utc(event.executed_at),
        }
    if isinstance(event, TechnicianReconciliationSessionCommitted):
        return {
            "session_id": event.session_id.value,
            "mode": event.mode,
            "anchor_at": _as_utc(event.anchor_at),
            "period_ids": list(event.period_ids),
            "deferred_period_ids": list(event.deferred_period_ids),
            "warehouse_inventory_id": event.warehouse_inventory_id,
            "warehouse_inventory_moment": (
                _as_utc(event.warehouse_inventory_moment)
                if event.warehouse_inventory_moment is not None
                else None
            ),
            "warehouse_delta_by_sku": _money_map(event.warehouse_delta_by_sku),
            "warehouse_source": event.warehouse_source,
            "warehouse_transfer_refs": _transfer_refs_to_payload(event.warehouse_transfer_refs),
            "ledger_balance_before": _money_map(event.ledger_balance_before),
            "cleared_by_sku": _money_map(event.cleared_by_sku),
            "residual_by_sku": _money_map(event.residual_by_sku),
            "finalized_at": _as_utc(event.finalized_at),
            "executed_at": _as_utc(event.executed_at),
        }
    return {
        "session_id": event.session_id.value,
        "period_ids": list(event.period_ids),
        "cleared_by_sku": _money_map(event.cleared_by_sku),
        "residual_by_sku": _money_map(event.residual_by_sku),
    }


@beartype
def settlement_event_from_document(document: dict[str, Any]) -> SettlementEvent:
    event_type = document["event_type"]
    payload = document["payload"]
    event_id = EventId(document["event_id"])
    technician_id = TechnicianId(document["aggregate_id"])
    occurred_at = _as_utc(document["occurred_at"])
    if event_type == PeriodAccountabilityRecorded.__name__:
        return PeriodAccountabilityRecorded(
            event_id=event_id,
            accountability_id=AccountabilityId(payload["accountability_id"]),
            technician_id=technician_id,
            period_id=payload["period_id"],
            machine_id=MachineId(payload["machine_id"]),
            delta_by_sku=_money_map_from(payload["delta_by_sku"]),
            closed_at=_as_utc(payload["closed_at"]),
            occurred_at=occurred_at,
        )
    if event_type == TechnicianReconciliationSessionCompleted.__name__:
        moment = payload["warehouse_inventory_moment"]
        return TechnicianReconciliationSessionCompleted(
            event_id=event_id,
            session_id=ReconciliationSessionId(payload["session_id"]),
            technician_id=technician_id,
            mode=payload["mode"],
            anchor_at=_as_utc(payload["anchor_at"]),
            period_ids=tuple(payload["period_ids"]),
            deferred_period_ids=tuple(payload["deferred_period_ids"]),
            warehouse_inventory_id=payload["warehouse_inventory_id"],
            warehouse_inventory_moment=_as_utc(moment) if moment is not None else None,
            warehouse_delta_by_sku=_money_map_from(payload["warehouse_delta_by_sku"]),
            warehouse_source=payload["warehouse_source"],
            warehouse_transfer_refs=_transfer_refs_from_payload(payload["warehouse_transfer_refs"]),
            ledger_balance_before=_money_map_from(payload["ledger_balance_before"]),
            residual_by_sku=_money_map_from(payload["residual_by_sku"]),
            finalized_at=_as_utc(payload["finalized_at"]),
            occurred_at=occurred_at,
            executed_at=_as_utc(payload["executed_at"]),
        )
    if event_type == TechnicianReconciliationSessionCommitted.__name__:
        moment = payload["warehouse_inventory_moment"]
        return TechnicianReconciliationSessionCommitted(
            event_id=event_id,
            session_id=ReconciliationSessionId(payload["session_id"]),
            technician_id=technician_id,
            mode=payload["mode"],
            anchor_at=_as_utc(payload["anchor_at"]),
            period_ids=tuple(payload["period_ids"]),
            deferred_period_ids=tuple(payload["deferred_period_ids"]),
            warehouse_inventory_id=payload["warehouse_inventory_id"],
            warehouse_inventory_moment=_as_utc(moment) if moment is not None else None,
            warehouse_delta_by_sku=_money_map_from(payload["warehouse_delta_by_sku"]),
            warehouse_source=payload["warehouse_source"],
            warehouse_transfer_refs=_transfer_refs_from_payload(payload["warehouse_transfer_refs"]),
            ledger_balance_before=_money_map_from(payload["ledger_balance_before"]),
            cleared_by_sku=_money_map_from(payload["cleared_by_sku"]),
            residual_by_sku=_money_map_from(payload["residual_by_sku"]),
            finalized_at=_as_utc(payload["finalized_at"]),
            occurred_at=occurred_at,
            executed_at=_as_utc(payload["executed_at"]),
        )
    if event_type == TechnicianLedgerClearedByReconciliation.__name__:
        return TechnicianLedgerClearedByReconciliation(
            event_id=event_id,
            session_id=ReconciliationSessionId(payload["session_id"]),
            technician_id=technician_id,
            period_ids=tuple(payload["period_ids"]),
            cleared_by_sku=_money_map_from(payload["cleared_by_sku"]),
            residual_by_sku=_money_map_from(payload["residual_by_sku"]),
            occurred_at=occurred_at,
        )
    raise ValueError(f"Unknown settlement event_type: {event_type}")
