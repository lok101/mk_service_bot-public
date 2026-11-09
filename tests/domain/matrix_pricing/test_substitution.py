from __future__ import annotations

import pytest

from src.domain.matrix_pricing import (
    SubstitutionDecision,
    decide_substitution,
    detect_pending_product_swap,
)


@pytest.mark.parametrize(
    ("stock", "blocked", "reason", "effective"),
    [
        (1, True, "stock_positive", "OLD"),
        (None, True, "stock_unknown", "OLD"),
        (0, False, None, "NEW"),
    ],
)
def test_decide_substitution_maps_stock_to_decision(
    stock: int | None,
    blocked: bool,
    reason: str | None,
    effective: str,
) -> None:
    decision = decide_substitution(
        desired_product="NEW",
        current_product="OLD",
        observed_stock=stock,
    )
    assert decision == SubstitutionDecision(
        effective_product=effective,
        blocked=blocked,
        block_reason=reason,
        observed_stock=stock,
    )


def test_decide_substitution_allows_product_to_empty_when_stock_is_zero() -> None:
    assert (
        decide_substitution(
            desired_product=None,
            current_product="OLD",
            observed_stock=0,
        ).effective_product
        is None
    )


@pytest.mark.parametrize(
    ("desired", "snapshot", "pending"),
    [
        ("NEW", None, False),
        (None, None, False),
        ("SAME", "SAME", False),
        ("NEW", "OLD", True),
        (None, "OLD", True),
    ],
)
def test_detect_pending_product_swap(
    desired: str | None,
    snapshot: str | None,
    pending: bool,
) -> None:
    assert (
        detect_pending_product_swap(
            desired_product=desired,
            snapshot_product=snapshot,
        )
        is pending
    )
