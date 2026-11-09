from __future__ import annotations

from beartype import beartype

from src.application.matrix_automation import extract_vending_machine_code


@beartype
def extract_machine_code_from_shop_name(shop_name: str) -> str | None:
    """Extract ``[NNN]`` machine_code from Kit Shop ``ShopName`` (reuse vending helper)."""
    return extract_vending_machine_code(shop_name)
