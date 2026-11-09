from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from beartype import beartype

SYNTHETIC_ZERO_BASELINE_ID = "synthetic_zero_baseline"


class TransferDirection(StrEnum):
    SUPPLY_IN = "supply_in"
    SUPPLY_RETURN = "supply_return"


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseLine:
    sku: str
    quantity_base: Decimal

    def __post_init__(self) -> None:
        if not self.sku.strip():
            raise ValueError("SKU must not be empty")
        if self.quantity_base <= 0:
            raise ValueError("Warehouse line quantity must be positive")


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseDelta:
    current_inventory_id: str
    current_inventory_moment: datetime
    previous_inventory_id: str
    previous_inventory_moment: datetime
    actual_by_sku: dict[str, Decimal]
    calculated_by_sku: dict[str, Decimal]
    delta_by_sku: dict[str, Decimal]
    transfer_document_ids: tuple[str, ...]
    transfer_content_hashes: tuple[str, ...]
    previous_actual_by_sku: dict[str, Decimal]
    supply_in_by_sku: dict[str, Decimal]
    returns_by_sku: dict[str, Decimal]
    loadings_by_sku: dict[str, Decimal]
