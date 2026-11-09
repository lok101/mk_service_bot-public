from __future__ import annotations

from decimal import Decimal

from tests.application.matrix_automation.substitution_guard.fakes import (
    _build_one,
)

from src.application.matrix_automation.sku_stats import sku_stats_from_lines


def test_blocked_swap_reprices_current_sku_and_counts_only_product_swap_blocked() -> None:
    line = _build_one(
        desired="NEW",
        desired_name="Новый",
        current="OLD",
        current_name="Старый",
        current_snapshot_price="60",
        stock=2,
        purchase_attributes={"OLD": ("80", 15), "NEW": ("10", 10)},
        guard_enabled=True,
    )
    assert line.product_code == "OLD"
    assert line.product_name == "Старый"
    assert line.deploy_price == Decimal("100")
    assert line.capacity == 15
    assert line.outcome == "product_swap_blocked"
    assert line.reason == "stock_positive"
    assert line.desired_product == "NEW"
    assert line.strong_price_increase is False
    assert line.baseline_price is None
    stats = sku_stats_from_lines((line,))
    assert stats.product_swap_blocked == 1
    assert stats.applied == 0
    assert stats.strong_price_increase == 0


def test_blocked_line_delta_fail_keeps_atomic_snapshot_but_guard_outcome() -> None:
    line = _build_one(
        desired="NEW",
        current="OLD",
        current_snapshot_price="100",
        current_snapshot_capacity=12,
        stock=2,
        purchase_attributes={"OLD": ("1", 99), "NEW": ("10", 10)},
        guard_enabled=True,
    )
    assert (line.deploy_price, line.capacity) == (Decimal("100"), 12)
    assert (line.outcome, line.reason) == ("product_swap_blocked", "stock_positive")
    assert sku_stats_from_lines((line,)).kept_previous == 0
