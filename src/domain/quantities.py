from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Literal

from beartype import beartype

from src.domain.form_submission import FormSubmissionPurpose

LoadInputUnit = Literal["package"]


@beartype
class QuantityInputMode(Enum):
    BASE_STOCK = "base_stock"
    PACKAGE_COUNT = "package_count"


@beartype
def mode_from_form_purpose(purpose: FormSubmissionPurpose | str) -> QuantityInputMode:
    normalized = str(purpose)
    if normalized == "revision":
        return QuantityInputMode.BASE_STOCK
    if normalized in {"loading", "technician_warehouse_inventory"}:
        return QuantityInputMode.PACKAGE_COUNT
    raise ValueError(f"Unknown form purpose for quantity mode: {purpose!r}")


@beartype
def packages_to_base_quantity(*, packages: Decimal, pack_size: Decimal) -> Decimal:
    if pack_size <= 0:
        raise ValueError(f"pack_size must be positive, got {pack_size!r}")
    return packages * pack_size
