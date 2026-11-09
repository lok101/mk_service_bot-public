from __future__ import annotations

import re

from beartype import beartype

from src.domain.machine_sales import SaleKind

_SNACK_VM_CODE_RE = re.compile(r"^5\d{2}$")


@beartype
def is_snack_machine_code(vending_machine_code: str | None) -> bool:
    if vending_machine_code is None:
        return False
    return _SNACK_VM_CODE_RE.fullmatch(vending_machine_code) is not None


@beartype
def sale_kind_from_vending_machine_code(vending_machine_code: str | None) -> SaleKind:
    if vending_machine_code is None:
        return "unknown"
    if is_snack_machine_code(vending_machine_code):
        return "snack"
    return "coffee"
