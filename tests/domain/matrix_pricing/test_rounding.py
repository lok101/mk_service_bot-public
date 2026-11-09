from __future__ import annotations

from decimal import Decimal

from src.domain.matrix_pricing.rounding import round_up_to_last_digits


def test_empty_digits_ceils_to_ruble() -> None:
    assert round_up_to_last_digits(Decimal("114.3"), None) == 115


def test_allowed_4_9_order_independent() -> None:
    digits = frozenset({4, 9})
    assert round_up_to_last_digits(Decimal("114.0"), digits) == 114
    assert round_up_to_last_digits(Decimal("114.3"), digits) == 119
    assert round_up_to_last_digits(Decimal("115.2"), digits) == 119


def test_allowed_zero_rounds_to_tens() -> None:
    assert round_up_to_last_digits(Decimal("71.0"), frozenset({0})) == 80


def test_large_decimal_value_without_float_drift() -> None:
    raw = Decimal("999999999999.3")
    assert round_up_to_last_digits(raw, None) == 1_000_000_000_000
