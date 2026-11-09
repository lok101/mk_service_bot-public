from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.micromarket_loading.shop_name import extract_machine_code_from_shop_name
from src.application.micromarket_loading.template_sync import DesiredTemplateRow


@beartype
@dataclass(frozen=True, slots=True)
class ShopCandidate:
    shop_id: int
    shop_name: str
    template_id: int | None


@beartype
@dataclass(frozen=True, slots=True)
class LocationCandidate:
    location_id: int
    location_type: int


@beartype
@dataclass(frozen=True, slots=True)
class ProductCandidate:
    product_id: int
    vendor_code: str
    is_deleted: bool


@beartype
@dataclass(frozen=True, slots=True)
class GroupCandidate:
    group_id: int


@beartype
@dataclass(frozen=True, slots=True)
class PublishSnapshotLine:
    product_code: str
    price_rub: Decimal
    kit_group_id: int
    disabled: bool = False


@beartype
@dataclass(frozen=True, slots=True)
class PreflightOk:
    shop_id: int
    template_id: int
    location_id: int
    rows: tuple[DesiredTemplateRow, ...]


@beartype
@dataclass(frozen=True, slots=True)
class PreflightError:
    message: str


@runtime_checkable
class MatrixWriteSpy(Protocol):
    def add_category(self, *, template_id: int, category_id: int) -> None: ...

    def remove_product(self, *, template_id: int, product_id: int) -> None: ...

    def add_product(
        self,
        *,
        template_id: int,
        product_id: int,
        price_rub: Decimal,
        category_id: int,
        location_id: int,
        disabled: bool = False,
    ) -> None: ...

    def add_command(self, *, shop_id: int) -> None: ...


@beartype
def prepare_shop_list_write(
    *,
    machine_code: str,
    shops: Sequence[ShopCandidate],
    locations: Sequence[LocationCandidate],
    products: Sequence[ProductCandidate],
    groups: Sequence[GroupCandidate],
    lines: Sequence[PublishSnapshotLine],
    writer: MatrixWriteSpy,
) -> PreflightOk | PreflightError:
    _ = writer  # Fragment 03: preflight never writes; writer is for caller contract.
    matched = [
        shop
        for shop in shops
        if extract_machine_code_from_shop_name(shop.shop_name) == machine_code
    ]
    if len(matched) != 1:
        return PreflightError("Магазин Kit Shop для этого аппарата не найден")
    shop = matched[0]
    if shop.template_id is None:
        return PreflightError("У магазина нет шаблона матрицы")
    showcases = [loc for loc in locations if loc.location_type == 2]
    if len(showcases) != 1:
        return PreflightError("Нужна одна витрина")
    showcase = showcases[0]
    group_ids = {group.group_id for group in groups}
    rows: list[DesiredTemplateRow] = []
    for line in lines:
        live = [
            product
            for product in products
            if product.vendor_code == line.product_code and not product.is_deleted
        ]
        if len(live) != 1:
            return PreflightError(f"Товар {line.product_code} не найден в Kit Shop")
        if line.kit_group_id not in group_ids:
            return PreflightError(f"Группа товара {line.product_code} не найдена в Kit Shop")
        rows.append(
            DesiredTemplateRow(
                live[0].product_id,
                line.price_rub,
                line.kit_group_id,
                showcase.location_id,
                line.disabled,
            )
        )
    return PreflightOk(
        shop_id=shop.shop_id,
        template_id=shop.template_id,
        location_id=showcase.location_id,
        rows=tuple(rows),
    )
