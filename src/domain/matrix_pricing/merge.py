from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from beartype import beartype

SkuPriceOutcome = Literal[
    "applied",
    "kept_previous",
    "skipped_no_baseline",
    "blocked_empty",
    "product_swap_blocked",
]


@beartype
@dataclass(frozen=True, slots=True)
class SnapshotLine:
    product_code: str | None
    product_name: str
    deploy_price: Decimal
    capacity: int


@beartype
@dataclass(frozen=True, slots=True)
class SkuPriceMergeResult:
    outcome: SkuPriceOutcome
    deploy_price: Decimal | None = None
    reason: str | None = None
    strong_price_increase: bool = False


@beartype
def _is_product_change(*, catalog_product_code: str | None, snapshot: SnapshotLine | None) -> bool:
    if snapshot is None:
        return False
    return catalog_product_code != snapshot.product_code


@beartype
def _decrease_pct(*, baseline: Decimal, sell: Decimal) -> Decimal:
    return (baseline - sell) / baseline * Decimal("100")


@beartype
def _increase_pct(*, baseline: Decimal, sell: Decimal) -> Decimal:
    return (sell - baseline) / baseline * Decimal("100")


@beartype
def merge_sku_price(
    *,
    calculated_sell: Decimal,
    purchase_valid: bool,
    capacity_valid: bool,
    catalog_product_code: str | None,
    snapshot: SnapshotLine | None,
    is_first_run: bool,
    has_baseline_line: bool,
    max_price_delta_pct: Decimal,
) -> SkuPriceMergeResult:
    validation_ok = purchase_valid and capacity_valid

    if snapshot is not None and _is_product_change(
        catalog_product_code=catalog_product_code,
        snapshot=snapshot,
    ):
        if validation_ok:
            return SkuPriceMergeResult(
                outcome="applied",
                deploy_price=calculated_sell,
            )
        return SkuPriceMergeResult(outcome="skipped_no_baseline")

    if not validation_ok:
        if snapshot is not None and snapshot.product_code == catalog_product_code:
            return SkuPriceMergeResult(
                outcome="kept_previous",
                deploy_price=snapshot.deploy_price,
                reason="validation_failed",
            )
        return SkuPriceMergeResult(outcome="skipped_no_baseline")

    if is_first_run or not has_baseline_line:
        return SkuPriceMergeResult(
            outcome="applied",
            deploy_price=calculated_sell,
        )

    assert snapshot is not None
    baseline = snapshot.deploy_price

    if max_price_delta_pct <= 0:
        return SkuPriceMergeResult(
            outcome="applied",
            deploy_price=calculated_sell,
        )

    if calculated_sell < baseline:
        decrease = _decrease_pct(baseline=baseline, sell=calculated_sell)
        if decrease > max_price_delta_pct:
            return SkuPriceMergeResult(
                outcome="kept_previous",
                deploy_price=baseline,
                reason="max_delta_decrease_exceeded",
            )
        return SkuPriceMergeResult(
            outcome="applied",
            deploy_price=calculated_sell,
        )

    if calculated_sell > baseline:
        increase = _increase_pct(baseline=baseline, sell=calculated_sell)
        if increase > max_price_delta_pct:
            return SkuPriceMergeResult(
                outcome="applied",
                deploy_price=calculated_sell,
                reason="strong_price_increase_noted",
                strong_price_increase=True,
            )

    return SkuPriceMergeResult(
        outcome="applied",
        deploy_price=calculated_sell,
    )
