from __future__ import annotations

from datetime import UTC, datetime

from beartype import beartype

from src.application.machine_operations.ports import DomainEventPublisher
from src.domain.ids import EventId, TechnicianId
from src.domain.technician_settlement.portion_events import (
    SettlementPortionReconcileRequested,
    SettlementPortionSalesVerifyRequested,
    SettlementPortionSyncTransfersRequested,
    portion_event_id,
)
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted


@beartype
def enqueue_portion_sync_transfers(
    *,
    event: TechnicianWarehouseInventoryCounted,
    publisher: DomainEventPublisher,
    occurred_at: datetime | None = None,
) -> None:
    now = occurred_at if occurred_at is not None else datetime.now(tz=UTC)
    publisher.publish(
        SettlementPortionSyncTransfersRequested(
            event_id=EventId(
                portion_event_id(
                    event.technician_id.value,
                    event.inventory_id,
                    "sync",
                ),
            ),
            technician_id=event.technician_id,
            warehouse_inventory_id=event.inventory_id,
            warehouse_inventory_moment=event.counted_at,
            occurred_at=now,
        ),
    )


@beartype
def enqueue_portion_sales_verify(
    *,
    publisher: DomainEventPublisher,
    technician_id: TechnicianId,
    warehouse_inventory_id: str,
    warehouse_inventory_moment: datetime,
    occurred_at: datetime | None = None,
) -> None:
    now = occurred_at if occurred_at is not None else datetime.now(tz=UTC)
    publisher.publish(
        SettlementPortionSalesVerifyRequested(
            event_id=EventId(
                portion_event_id(
                    technician_id.value,
                    warehouse_inventory_id,
                    "sales",
                ),
            ),
            technician_id=technician_id,
            warehouse_inventory_id=warehouse_inventory_id,
            warehouse_inventory_moment=warehouse_inventory_moment,
            occurred_at=now,
        ),
    )


@beartype
def enqueue_portion_reconcile(
    *,
    publisher: DomainEventPublisher,
    technician_id: TechnicianId,
    warehouse_inventory_id: str,
    warehouse_inventory_moment: datetime,
    occurred_at: datetime | None = None,
    not_before: datetime | None = None,
) -> None:
    now = occurred_at if occurred_at is not None else datetime.now(tz=UTC)
    publisher.publish(
        SettlementPortionReconcileRequested(
            event_id=EventId(
                portion_event_id(
                    technician_id.value,
                    warehouse_inventory_id,
                    "reconcile",
                ),
            ),
            technician_id=technician_id,
            warehouse_inventory_id=warehouse_inventory_id,
            warehouse_inventory_moment=warehouse_inventory_moment,
            occurred_at=now,
            not_before=not_before,
        ),
    )
