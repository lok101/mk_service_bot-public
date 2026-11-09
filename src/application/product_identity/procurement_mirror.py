from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class ProcurementMirror:
    catalog_code: str
    supplier_id: str | None
    supplier_name: str | None
    last_buy_price: Decimal | None
    supply_moment: datetime | None
    synced_at: datetime
    package_quantity: Decimal | None = None
    supplier_product_name: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class ProcurementSupplySnapshot:
    """Successful fetch payload before writing `synced_at` into the store."""

    catalog_code: str
    supplier_id: str | None
    supplier_name: str | None
    last_buy_price: Decimal | None
    supply_moment: datetime | None
    package_quantity: Decimal | None = None
    supplier_product_name: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class ProcurementFetchFailed:
    catalog_code: str
