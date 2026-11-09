from __future__ import annotations

from beartype import beartype

from src.application.matrix_automation.models import MatrixDeployPayloadLine, SkuStats


@beartype
def sku_stats_from_lines(lines: tuple[MatrixDeployPayloadLine, ...]) -> SkuStats:
    applied = 0
    kept_previous = 0
    skipped_no_baseline = 0
    strong_price_increase = 0
    blocked_empty = 0
    product_swap_blocked = 0
    for line in lines:
        if line.outcome == "applied":
            applied += 1
            if line.strong_price_increase and line.baseline_price is not None:
                strong_price_increase += 1
        elif line.outcome == "kept_previous":
            kept_previous += 1
        elif line.outcome == "skipped_no_baseline":
            skipped_no_baseline += 1
        elif line.outcome == "blocked_empty":
            blocked_empty += 1
        elif line.outcome == "product_swap_blocked":
            product_swap_blocked += 1
    return SkuStats(
        applied=applied,
        kept_previous=kept_previous,
        skipped_no_baseline=skipped_no_baseline,
        strong_price_increase=strong_price_increase,
        blocked_empty=blocked_empty,
        product_swap_blocked=product_swap_blocked,
    )
