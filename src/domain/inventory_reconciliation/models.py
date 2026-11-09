from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.domain.quantities import LoadInputUnit


@beartype
@dataclass(frozen=True, slots=True)
class PeriodRevisionStock:
    lines: tuple[tuple[str, Decimal], ...]


@beartype
@dataclass(frozen=True, slots=True)
class PeriodLoadLine:
    product_code: str
    occurred_at: datetime
    input_quantity: Decimal
    input_unit: LoadInputUnit
    pack_size: Decimal
    base_quantity: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class PeriodSaleLine:
    product_code: str
    quantity: Decimal
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class ReconciliationLine:
    product_code: str
    actual_prev: Decimal
    actual: Decimal
    calculated: Decimal
    delta: Decimal
    loads_total: Decimal = Decimal("0")
    sales_total: Decimal = Decimal("0")


@beartype
@dataclass(frozen=True, slots=True)
class PeriodReconciliationResult:
    lines_by_product: dict[str, ReconciliationLine]
