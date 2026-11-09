from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

SupplyOrderLineCategory = Literal[2, 3]


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketSupplyOrderLine:
    product_code: str
    need_qty: Decimal
    category: SupplyOrderLineCategory
    name: str = ""
    supplier_name: str | None = None
    last_buy_price: Decimal | None = None
    package_quantity: Decimal | None = None
    supplier_product_name: str | None = None
    gap_qty: Decimal = Decimal("0")
    forecast_qty: Decimal = Decimal("0")


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketSupplyOrderMachine:
    machine_id: str
    lines: tuple[MicromarketSupplyOrderLine, ...]


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketSupplyOrder:
    order_id: str
    created_at: datetime
    expected_arrival_at: datetime
    machines: tuple[MicromarketSupplyOrderMachine, ...]
