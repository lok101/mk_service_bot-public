from __future__ import annotations

from src.application.micromarket_loading.shop_name import extract_machine_code_from_shop_name


def test_extract_machine_code_from_shop_name() -> None:
    assert extract_machine_code_from_shop_name("Мегас [701]") == "701"
    assert extract_machine_code_from_shop_name("[701] офис") == "701"


def test_extract_machine_code_from_shop_name_miss() -> None:
    assert extract_machine_code_from_shop_name("Мегас без кода") is None
    assert extract_machine_code_from_shop_name("") is None
