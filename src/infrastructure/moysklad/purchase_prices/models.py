from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype


@beartype
@dataclass(frozen=True, slots=True)
class PurchaseAttributes:
    buy_price: str
    volume: int


@beartype
@dataclass(frozen=True, slots=True)
class PurchaseAttributesBatchResult:
    attributes: dict[str, PurchaseAttributes]
    cards_found: int
    supply_http_failed: frozenset[str] = frozenset()


@beartype
@dataclass(frozen=True, slots=True)
class LastSupplyProcurementRow:
    catalog_code: str
    supplier_id: str | None
    supplier_name: str | None
    last_buy_price: Decimal | None
    supply_moment: datetime | None
    package_quantity: Decimal | None = None
    supplier_product_name: str | None = None
