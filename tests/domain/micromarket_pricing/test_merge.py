from __future__ import annotations

from decimal import Decimal

from src.domain.micromarket_pricing.merge import merge_calculated_price


def test_first_apply_without_baseline() -> None:
    """happy: no baseline → applied."""
    result = merge_calculated_price(
        calculated_sell=Decimal("120"),
        baseline_sell=None,
        max_price_delta_pct=Decimal("15"),
    )
    assert result.outcome == "applied"
    assert result.deploy_price == Decimal("120")


def test_strong_decrease_kept_previous() -> None:
    """edge: decrease > delta → keep previous."""
    result = merge_calculated_price(
        calculated_sell=Decimal("80"),
        baseline_sell=Decimal("100"),
        max_price_delta_pct=Decimal("15"),
    )
    assert result.outcome == "kept_previous"
    assert result.deploy_price == Decimal("100")
    assert result.reason == "max_delta_decrease_exceeded"


def test_strong_increase_applied_with_note() -> None:
    """edge: increase > delta → apply + note."""
    result = merge_calculated_price(
        calculated_sell=Decimal("120"),
        baseline_sell=Decimal("100"),
        max_price_delta_pct=Decimal("15"),
    )
    assert result.outcome == "applied"
    assert result.deploy_price == Decimal("120")
    assert result.reason == "strong_price_increase_noted"
    assert result.strong_price_increase is True


def test_small_change_applied() -> None:
    """happy: within delta → applied."""
    result = merge_calculated_price(
        calculated_sell=Decimal("105"),
        baseline_sell=Decimal("100"),
        max_price_delta_pct=Decimal("15"),
    )
    assert result.outcome == "applied"
    assert result.strong_price_increase is False


def test_delta_disabled_always_applied() -> None:
    """edge: max_delta_pct <= 0 → always apply."""
    result = merge_calculated_price(
        calculated_sell=Decimal("50"),
        baseline_sell=Decimal("100"),
        max_price_delta_pct=Decimal("0"),
    )
    assert result.outcome == "applied"
    assert result.deploy_price == Decimal("50")
