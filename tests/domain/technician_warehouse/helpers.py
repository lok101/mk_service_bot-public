from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse import (
    TechnicianWarehouse,
    TechnicianWarehouseLine,
    TechnicianWarehouseLoadingObserved,
    TechnicianWarehouseTransferObserved,
    TransferDirection,
)

_TECHNICIAN_ID = TechnicianId("tech-1")
_T0 = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
_T1 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
_T2 = datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
_T3 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
_T4 = datetime(2026, 7, 1, 13, 0, tzinfo=UTC)
_SYNTHETIC_MOMENT = datetime(1, 1, 1, tzinfo=UTC)


def _line(quantity: str) -> tuple[TechnicianWarehouseLine, ...]:
    return (TechnicianWarehouseLine(sku="coffee", quantity_base=Decimal(quantity)),)


def _supply_event(
    external_document_id: str,
    quantity: str,
    direction: TransferDirection = TransferDirection.SUPPLY_IN,
    *,
    updated_at: datetime | None = None,
    observed_at: datetime | None = None,
    content_hash: str | None = None,
) -> TechnicianWarehouseTransferObserved:
    moment = updated_at or observed_at or _T1
    resolved_updated_at = updated_at or moment
    resolved_observed_at = observed_at or moment
    resolved_content_hash = content_hash or f"{external_document_id}:{quantity}:{direction.value}"
    return TechnicianWarehouseTransferObserved(
        event_id=EventId(f"event-transfer-{external_document_id}-{quantity}"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=resolved_observed_at,
        external_document_id=external_document_id,
        moment=moment,
        updated_at=resolved_updated_at,
        observed_at=resolved_observed_at,
        content_hash=resolved_content_hash,
        direction=direction,
        lines=_line(quantity),
    )


def _loading_event(
    source_event_id: str,
    quantity: str,
    *,
    submitted_at: datetime | None = None,
) -> TechnicianWarehouseLoadingObserved:
    resolved_submitted_at = submitted_at or _T2
    return TechnicianWarehouseLoadingObserved(
        event_id=EventId(f"event-loading-{source_event_id}"),
        technician_id=_TECHNICIAN_ID,
        occurred_at=resolved_submitted_at,
        source_event_id=source_event_id,
        machine_id=MachineId("vm-01"),
        submitted_at=resolved_submitted_at,
        lines=_line(quantity),
    )


def _warehouse_with_baseline(actual_by_sku: dict[str, Decimal]) -> TechnicianWarehouse:
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-baseline",
        form_token="baseline-token",
        counted_at=_T1,
        actual_by_sku=actual_by_sku,
        baseline=False,
    )
    warehouse.clear_pending_events()
    return warehouse


def _closed_warehouse() -> TechnicianWarehouse:
    ret = _supply_event("move-ret", "10", TransferDirection.SUPPLY_RETURN, updated_at=_T2)
    warehouse = TechnicianWarehouse.empty(_TECHNICIAN_ID)
    warehouse.count_inventory(
        inventory_id="inv-baseline",
        form_token="token-baseline",
        counted_at=_T0,
        actual_by_sku={"coffee": Decimal("10")},
        baseline=False,
    )
    warehouse.observe_transfer(ret)
    warehouse.close_exit(
        closed_at=_T4,
        return_external_document_id="move-ret",
        return_content_hash=ret.content_hash,
    )
    warehouse.clear_pending_events()
    return warehouse
