from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum

from beartype import beartype


class KitMatrixCommandCode(IntEnum):
    LOAD_MATRIX = 3
    APPLY_MATRIX = 4


@dataclass(frozen=True, slots=True)
class KitVendingMachineRecord:
    vending_machine_id: int
    vending_machine_name: str


@dataclass(frozen=True, slots=True)
class KitVMStateRecord:
    vending_machine_id: int
    raw: dict[str, object]


@dataclass(frozen=True, slots=True)
class KitMatrixPosition:
    line_number: int
    goods_name: str
    price: str
    price2: str
    max_count: int

    @beartype
    def to_request(self) -> dict[str, object]:
        return {
            "LineNumber": self.line_number,
            "GoodsName": self.goods_name,
            "Price": self.price,
            "Price2": self.price2,
            "MaxCount": self.max_count,
        }


@beartype
def format_kit_decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


KIT_GOODS_NAME_MAX_LENGTH = 64


@beartype
def format_kit_goods_name(product_code: str, product_name: str) -> str:
    raw = f"{product_code.strip()} | {product_name.strip()}"
    if len(raw) <= KIT_GOODS_NAME_MAX_LENGTH:
        return raw
    ellipsis = "..."
    cutoff = KIT_GOODS_NAME_MAX_LENGTH - len(ellipsis)
    return raw[:cutoff] + ellipsis


@beartype
def build_matrix_position(
    *,
    line_number: int,
    product_name: str,
    product_code: str | None,
    deploy_price: Decimal,
    capacity: int,
    blocking_label: str,
) -> KitMatrixPosition:
    price = format_kit_decimal(deploy_price)
    max_count = capacity
    if product_code is None:
        goods_name = blocking_label.strip()
        max_count = 0
    else:
        goods_name = format_kit_goods_name(product_code, product_name)
    return KitMatrixPosition(
        line_number=line_number,
        goods_name=goods_name,
        price=price,
        price2=price,
        max_count=max_count,
    )
