from __future__ import annotations

from src.application.matrix_automation import extract_vending_machine_code
from src.infrastructure.integrations.kitvending.api_models.enums import VendingMachineKind
from src.infrastructure.integrations.kitvending.parsing.utils import (
    compute_vending_machine_type,
    extract_product_code,
    is_product_name_placeholder,
    is_product_zero_placeholder,
    try_product_code_from_placeholder_name,
)


def test_snack_when_machine_code_matches_5xx() -> None:
    assert compute_vending_machine_type("501") == VendingMachineKind.SNACK
    assert compute_vending_machine_type("599") == VendingMachineKind.SNACK


def test_coffee_when_code_not_5xx_three_digits() -> None:
    assert compute_vending_machine_type("129") == VendingMachineKind.COFFEE
    assert compute_vending_machine_type("50") == VendingMachineKind.COFFEE
    assert compute_vending_machine_type("5012") == VendingMachineKind.COFFEE


def test_not_defined_when_code_missing() -> None:
    assert compute_vending_machine_type(None) == VendingMachineKind.NOT_DEFINED


def test_is_product_name_placeholder_positive() -> None:
    assert is_product_name_placeholder("Товар 5") is True
    assert is_product_name_placeholder("  Товар 12  ") is True


def test_is_product_name_placeholder_negative() -> None:
    assert is_product_name_placeholder("товар 5") is False
    assert is_product_name_placeholder("Товар") is False
    assert is_product_name_placeholder("Товар x") is False
    assert is_product_name_placeholder("123|Name") is False
    assert is_product_name_placeholder("Товар 1 extra") is False


def test_is_product_zero_placeholder_positive() -> None:
    assert is_product_zero_placeholder("Товар 0") is True
    assert is_product_zero_placeholder("  Товар 0  ") is True


def test_is_product_zero_placeholder_negative() -> None:
    assert is_product_zero_placeholder("Товар 1") is False
    assert is_product_zero_placeholder("Товар 00") is False
    assert is_product_zero_placeholder("товар 0") is False


def test_try_product_code_from_placeholder_name_four_digit_two_prefix() -> None:
    assert try_product_code_from_placeholder_name("Товар 2311") == "2311"
    assert try_product_code_from_placeholder_name("  Товар 2101  ") == "2101"
    assert try_product_code_from_placeholder_name("Товар 2000") == "2000"


def test_try_product_code_from_placeholder_name_not_applicable() -> None:
    assert try_product_code_from_placeholder_name("Товар 5") is None
    assert try_product_code_from_placeholder_name("Товар 231") is None
    assert try_product_code_from_placeholder_name("Товар 23111") is None
    assert try_product_code_from_placeholder_name("Товар 3999") is None
    assert try_product_code_from_placeholder_name("123|X") is None
    assert try_product_code_from_placeholder_name("Товар 0") is None


def test_extract_vending_machine_code() -> None:
    assert extract_vending_machine_code("Кофе [129] офис") == "129"
    assert extract_vending_machine_code("[501] ТЦ") == "501"
    assert extract_vending_machine_code("без кода") is None


def test_parse_sheet_machine_code() -> None:
    from src.application.matrix_automation.sheets.machine_code import parse_sheet_machine_code

    assert parse_sheet_machine_code("514") == "514"
    assert parse_sheet_machine_code("[512]") == "512"
    assert parse_sheet_machine_code("Аппарат [777]") == "777"
    assert parse_sheet_machine_code("битый") is None
    assert parse_sheet_machine_code("51") is None


def test_extract_product_code_pipe() -> None:
    assert extract_product_code("2312 | Капучино") == "2312"
    assert extract_product_code("PRODUCT01 | Тестовый товар") == "PRODUCT01"
    assert extract_product_code("no pipe") is None
    assert extract_product_code("bad code | Name") is None
