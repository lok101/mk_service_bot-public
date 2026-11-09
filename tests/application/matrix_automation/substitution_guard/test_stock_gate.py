from __future__ import annotations

import pytest
from tests.application.matrix_automation.substitution_guard.fakes import (
    _build_one,
)


def test_pending_swap_without_stock_provider_raises_clear_error() -> None:
    with pytest.raises(ValueError, match="MatrixStockProvider required"):
        _build_one(
            desired="NEW",
            current="OLD",
            guard_enabled=True,
            provider=None,
            stock=None,
        )


@pytest.mark.parametrize(
    ("stock", "reason"),
    [(3, "stock_positive"), (None, "stock_unknown")],
)
def test_code_to_code_is_blocked_for_positive_or_unknown_stock(
    stock: int | None,
    reason: str,
) -> None:
    line = _build_one(desired="NEW", current="OLD", stock=stock, guard_enabled=True)
    assert (line.product_code, line.outcome, line.reason) == ("OLD", "product_swap_blocked", reason)


def test_code_to_code_is_allowed_when_stock_is_zero() -> None:
    line = _build_one(desired="NEW", current="OLD", stock=0, guard_enabled=True)
    assert (line.product_code, line.outcome) == ("NEW", "applied")


def test_product_to_empty_is_blocked_while_stock_positive() -> None:
    line = _build_one(desired=None, current="OLD", stock=1, guard_enabled=True)
    assert (line.product_code, line.outcome) == ("OLD", "product_swap_blocked")


def test_product_to_empty_becomes_blocked_empty_when_stock_zero() -> None:
    line = _build_one(desired=None, current="OLD", stock=0, guard_enabled=True)
    assert (line.product_code, line.outcome) == (None, "blocked_empty")
