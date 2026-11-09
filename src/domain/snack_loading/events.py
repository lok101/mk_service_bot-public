from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.domain.ids import EventId

type CellKey = tuple[str, str, int]


@beartype
@dataclass(frozen=True, slots=True)
class SnackInventoryAccepted:
    event_id: EventId
    machine_code: str
    inventory_id: str
    as_of: datetime
    quantities: tuple[tuple[CellKey, Decimal], ...]
    product_by_key: tuple[tuple[CellKey, str], ...]
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class SnackSaleDeducted:
    event_id: EventId
    machine_code: str
    source_id: str
    cell_key: CellKey
    product_code: str
    quantity: Decimal
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class SnackLoadingApplied:
    event_id: EventId
    machine_code: str
    run_id: str
    move_id: str
    increments: tuple[tuple[CellKey, Decimal], ...]
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class SnackStockAnomalyRecorded:
    event_id: EventId
    machine_code: str
    source_id: str
    cell_key: CellKey
    requested_quantity: Decimal
    available_quantity: Decimal
    clamped_quantity: Decimal
    occurred_at: datetime


SnackStockEvent = (
    SnackInventoryAccepted | SnackSaleDeducted | SnackLoadingApplied | SnackStockAnomalyRecorded
)
