from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.domain.ids import EventId


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketInventoryAccepted:
    event_id: EventId
    machine_code: str
    inventory_id: str
    as_of: datetime
    quantities: tuple[tuple[str, Decimal], ...]
    occurred_at: datetime
    partial: bool = False


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketSaleDeducted:
    event_id: EventId
    machine_code: str
    sale_source_id: str
    product_code: str
    qty: Decimal
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketLoadingApplied:
    event_id: EventId
    machine_code: str
    loading_run_id: str
    lines: tuple[tuple[str, Decimal], ...]
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketStockAnomalyRecorded:
    event_id: EventId
    machine_code: str
    kind: str
    product_code: str
    detail: str
    sale_source_id: str
    requested_qty: Decimal
    available_qty: Decimal
    clamped_qty: Decimal
    occurred_at: datetime


MicromarketStockEvent = (
    MicromarketInventoryAccepted
    | MicromarketSaleDeducted
    | MicromarketLoadingApplied
    | MicromarketStockAnomalyRecorded
)
