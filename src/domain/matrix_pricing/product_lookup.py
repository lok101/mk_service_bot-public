from __future__ import annotations

from beartype import beartype

from src.domain.matrix_pricing.errors import UnknownProductName
from src.domain.matrix_pricing.result import Result


@beartype
def resolve_product_code(
    product_name: str,
    name_to_code: dict[str, str],
) -> Result[str, UnknownProductName]:
    normalized = product_name.strip()
    code = name_to_code.get(normalized)
    if code is None:
        return Result.err(UnknownProductName(product_name=normalized))
    return Result.ok(code)
