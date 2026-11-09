"""Pure domain logic for matrix pricing."""

from src.domain.matrix_pricing.blocking import build_blocking_empty_line
from src.domain.matrix_pricing.bounds import (
    MarginBounds,
    MatrixMultiplierBounds,
    ProductMultiplierBounds,
    validate_multiplier,
)
from src.domain.matrix_pricing.formula import BaseMarginParams, calculate_sell_price
from src.domain.matrix_pricing.merge import SkuPriceMergeResult, merge_sku_price
from src.domain.matrix_pricing.product_lookup import resolve_product_code
from src.domain.matrix_pricing.rounding import round_up_to_last_digits
from src.domain.matrix_pricing.substitution import (
    SubstitutionDecision,
    decide_substitution,
    detect_pending_product_swap,
)

__all__ = [
    "BaseMarginParams",
    "MarginBounds",
    "MatrixMultiplierBounds",
    "ProductMultiplierBounds",
    "SkuPriceMergeResult",
    "SubstitutionDecision",
    "build_blocking_empty_line",
    "calculate_sell_price",
    "decide_substitution",
    "detect_pending_product_swap",
    "merge_sku_price",
    "resolve_product_code",
    "round_up_to_last_digits",
    "validate_multiplier",
]
