from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

DEFAULT_PRODUCT_MULTIPLIER = Decimal("1")


@beartype
@dataclass(frozen=True, slots=True)
class MatrixSkuCatalogEntry:
    product_code: str
    display_name: str
    capacity: int
    product_multiplier: Decimal


@beartype
def is_matrix_ready(entry: MatrixSkuCatalogEntry) -> bool:
    return entry.capacity > 0 and bool(entry.display_name.strip())


@beartype
def resolve_product_multiplier(value: Decimal | None) -> Decimal:
    if value is None:
        return DEFAULT_PRODUCT_MULTIPLIER
    return value
