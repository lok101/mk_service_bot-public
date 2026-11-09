from __future__ import annotations

import re

from beartype import beartype

from src.infrastructure.integrations.kitvending.api_models.enums import VendingMachineKind

_PRODUCT_NAME_PLACEHOLDER = re.compile(r"Товар\s+\d+")
_PRODUCT_PLACEHOLDER_CAPTURE = re.compile(r"Товар\s+(\d+)")
_PRODUCT_ZERO_PLACEHOLDER = re.compile(r"Товар\s+0")
_SNACK_VM_CODE_RE = re.compile(r"^5\d{2}$")
_PIPE_PRODUCT_CODE = re.compile(r"^[A-Za-z0-9._-]+$")


@beartype
def is_product_name_placeholder(name: str) -> bool:
    """Имя вида «Товар <номер>», когда товар в продаже не удалось определить по названию."""
    return bool(_PRODUCT_NAME_PLACEHOLDER.fullmatch(name.strip()))


@beartype
def is_product_zero_placeholder(name: str) -> bool:
    """Плейсхолдер «Товар 0» — недопустимая позиция, отдельно от остальных «Товар N»."""
    return bool(_PRODUCT_ZERO_PLACEHOLDER.fullmatch(name.strip()))


@beartype
def try_product_code_from_placeholder_name(name: str) -> str | None:
    """Плейсхолдер «Товар N»: если N — 4 цифры с префиксом «2», вернуть N как код товара.

    Используется, когда MatrixId отсутствует или матрица не пришла в GetGoodsMatrices, но номер
    на самом деле совпадает с кодом товара в учётной системе (например 2311, 2101).
    """
    m = _PRODUCT_PLACEHOLDER_CAPTURE.fullmatch(name.strip())
    if not m:
        return None
    digits = m.group(1)
    if len(digits) == 4 and digits.startswith("2"):
        return digits
    return None


@beartype
def extract_product_code(product_name: str) -> str | None:
    if "|" not in product_name:
        return None

    left, _ = product_name.split("|", 1)
    left_stripped = left.strip()
    if not left_stripped:
        return None

    if left_stripped.isdigit():
        return left_stripped

    if _PIPE_PRODUCT_CODE.fullmatch(left_stripped):
        return left_stripped

    return None


@beartype
def compute_vending_machine_type(vending_machine_code: str | None) -> VendingMachineKind:
    if vending_machine_code is None:
        return VendingMachineKind.NOT_DEFINED
    if _SNACK_VM_CODE_RE.fullmatch(vending_machine_code):
        return VendingMachineKind.SNACK
    return VendingMachineKind.COFFEE
