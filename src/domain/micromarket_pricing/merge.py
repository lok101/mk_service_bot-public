from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from beartype import beartype

CalculatedPriceOutcome = Literal["applied", "kept_previous"]


@beartype
@dataclass(frozen=True, slots=True)
class CalculatedPriceMergeResult:
    outcome: CalculatedPriceOutcome
    deploy_price: Decimal
    reason: str | None = None
    strong_price_increase: bool = False


@beartype
def _decrease_pct(*, baseline: Decimal, sell: Decimal) -> Decimal:
    return (baseline - sell) / baseline * Decimal("100")


@beartype
def _increase_pct(*, baseline: Decimal, sell: Decimal) -> Decimal:
    return (sell - baseline) / baseline * Decimal("100")


@beartype
def merge_calculated_price(
    *,
    calculated_sell: Decimal,
    baseline_sell: Decimal | None,
    max_price_delta_pct: Decimal,
) -> CalculatedPriceMergeResult:
    if baseline_sell is None or max_price_delta_pct <= 0:
        return CalculatedPriceMergeResult(
            outcome="applied",
            deploy_price=calculated_sell,
        )

    baseline = baseline_sell
    if calculated_sell < baseline:
        decrease = _decrease_pct(baseline=baseline, sell=calculated_sell)
        if decrease > max_price_delta_pct:
            return CalculatedPriceMergeResult(
                outcome="kept_previous",
                deploy_price=baseline,
                reason="max_delta_decrease_exceeded",
            )
        return CalculatedPriceMergeResult(
            outcome="applied",
            deploy_price=calculated_sell,
        )

    if calculated_sell > baseline:
        increase = _increase_pct(baseline=baseline, sell=calculated_sell)
        if increase > max_price_delta_pct:
            return CalculatedPriceMergeResult(
                outcome="applied",
                deploy_price=calculated_sell,
                reason="strong_price_increase_noted",
                strong_price_increase=True,
            )

    return CalculatedPriceMergeResult(
        outcome="applied",
        deploy_price=calculated_sell,
    )
