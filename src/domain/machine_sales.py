from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.ids import MachineId

SaleKind = Literal["coffee", "snack", "unknown", "micromarket"]


@beartype
@dataclass(frozen=True, slots=True)
class MachineSale:
    source_id: str
    machine_id: MachineId
    product_code: str
    quantity: Decimal
    occurred_at: datetime
    ingested_at: datetime
    sale_kind: SaleKind = "unknown"
    kit_matrix_id: int | None = None
    kit_vending_machine_id: int | None = None
    kit_line_number: int | None = None
    machine_code: str | None = None
    resolve_status: str | None = None
    price: Decimal | None = None
    company_id: int | None = None
    kit_vending_company_id: int | None = None
    domain_product_id: str = ""
