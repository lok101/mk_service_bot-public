from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from beartype import beartype

from src.domain.ids import EventId, TechnicianId


@beartype
def portion_event_id(
    technician_id: str,
    inventory_id: str,
    step: Literal["sync", "sales", "reconcile"],
) -> str:
    return f"portion:{technician_id}:{inventory_id}:{step}"


@beartype
@dataclass(frozen=True, slots=True)
class SettlementPortionSyncTransfersRequested:
    event_id: EventId
    technician_id: TechnicianId
    warehouse_inventory_id: str
    warehouse_inventory_moment: datetime
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class SettlementPortionSalesVerifyRequested:
    event_id: EventId
    technician_id: TechnicianId
    warehouse_inventory_id: str
    warehouse_inventory_moment: datetime
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class SettlementPortionReconcileRequested:
    event_id: EventId
    technician_id: TechnicianId
    warehouse_inventory_id: str
    warehouse_inventory_moment: datetime
    occurred_at: datetime
    not_before: datetime | None = None


SettlementPortionEvent = (
    SettlementPortionSyncTransfersRequested
    | SettlementPortionSalesVerifyRequested
    | SettlementPortionReconcileRequested
)
