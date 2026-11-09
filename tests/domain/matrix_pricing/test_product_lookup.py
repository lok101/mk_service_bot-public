from __future__ import annotations

from src.domain.matrix_pricing.errors import UnknownProductName
from src.domain.matrix_pricing.product_lookup import resolve_product_code


def test_resolve_product_code_found() -> None:
    result = resolve_product_code("Кола", {"Кола": "MS-1"})
    assert result.is_ok()
    assert result.value == "MS-1"


def test_resolve_product_code_unknown() -> None:
    result = resolve_product_code("Missing", {})
    assert result.is_err()
    assert isinstance(result.error, UnknownProductName)
