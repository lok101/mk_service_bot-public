from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from beartype import beartype

SubstitutionBlockReason = Literal["stock_positive", "stock_unknown"]


@dataclass(frozen=True, slots=True)
class SubstitutionDecision:
    effective_product: str | None
    blocked: bool
    block_reason: SubstitutionBlockReason | None
    observed_stock: int | None


@beartype
def decide_substitution(
    *,
    desired_product: str | None,
    current_product: str,
    observed_stock: int | None,
) -> SubstitutionDecision:
    if observed_stock is None:
        return SubstitutionDecision(current_product, True, "stock_unknown", None)
    if observed_stock > 0:
        return SubstitutionDecision(current_product, True, "stock_positive", observed_stock)
    return SubstitutionDecision(desired_product, False, None, observed_stock)


@beartype
def detect_pending_product_swap(
    *,
    desired_product: str | None,
    snapshot_product: str | None,
) -> bool:
    return snapshot_product is not None and desired_product != snapshot_product
