from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.domain.matrix_pricing.merge import SkuPriceMergeResult


@beartype
@dataclass(frozen=True, slots=True)
class BlockingEmptyLine:
    line_number: int
    product_code: None
    product_name: str
    deploy_price: Decimal
    capacity: int
    outcome: str
    reason: None


@beartype
def build_blocking_empty_line(
    *,
    line_number: int,
    blocking_price: Decimal,
) -> BlockingEmptyLine:
    return BlockingEmptyLine(
        line_number=line_number,
        product_code=None,
        product_name="",
        deploy_price=blocking_price,
        capacity=0,
        outcome="blocked_empty",
        reason=None,
    )


@beartype
def blocking_empty_to_merge_result(line: BlockingEmptyLine) -> SkuPriceMergeResult:
    return SkuPriceMergeResult(
        outcome="blocked_empty",
        deploy_price=line.deploy_price,
    )
