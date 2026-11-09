from __future__ import annotations

from src.domain.machine_sales_classify import (
    is_snack_machine_code,
    sale_kind_from_vending_machine_code,
)


def test_snack_machine_code_starts_with_five() -> None:
    assert sale_kind_from_vending_machine_code("501") == "snack"


def test_coffee_machine_code_not_five_prefix() -> None:
    assert sale_kind_from_vending_machine_code("129") == "coffee"


def test_unknown_when_code_missing() -> None:
    assert sale_kind_from_vending_machine_code(None) == "unknown"


def test_short_five_prefix_is_coffee_not_snack() -> None:
    assert sale_kind_from_vending_machine_code("50") == "coffee"


def test_is_snack_machine_code_matches_sale_kind() -> None:
    assert is_snack_machine_code("501") is True
    assert sale_kind_from_vending_machine_code("501") == "snack"
    assert is_snack_machine_code("129") is False
    assert sale_kind_from_vending_machine_code("129") == "coffee"


def test_short_five_prefix_is_not_snack_machine() -> None:
    assert is_snack_machine_code("50") is False
    assert sale_kind_from_vending_machine_code("50") == "coffee"


def test_is_snack_machine_code_rejects_none_and_empty() -> None:
    assert is_snack_machine_code(None) is False
    assert is_snack_machine_code("") is False
