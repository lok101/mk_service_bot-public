from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.product_catalog import ProductUnit

EMPTY_NAME_TEXT = "Название не может быть пустым."
CARD_TAKEN_TEXT = "Карточка уже занята другим товаром."
CODE_MISSING_TEXT = "Кода нет в снимке."
NUMBER_NOT_ISSUED_TEXT = "Номер не выдан."
OTHER_CARD_TEXT = "У товара уже другая карточка."
SECOND_LINK_TEXT = "У товара уже другая карточка."
AMBIGUOUS_NAME_TEXT = "Несколько товаров с таким именем."
FILE_UNREADABLE_TEXT = "Файл не читается."
FILE_EMPTY_TEXT = "В файле нет строк товаров."
WRONG_CONTOUR_TEXT = "Товар другого контура — операция недоступна на этом экране."
PACKAGING_REQUIRED_TEXT = "Укажите единицу и размер упаковки."

DomainProductKind = Literal["micromarket", "coffee_ingredient", "coffee_drink"]
DomainProductContour = Literal["micromarket", "coffee"]


class DomainProductConflict(Exception):
    @beartype
    def __init__(self, field: str) -> None:
        super().__init__(field)
        self.field = field


class DomainProductRejected(Exception):
    @beartype
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@beartype
@dataclass(frozen=True, slots=True)
class CatalogProduct:
    code: str
    name: str
    archived: bool


@beartype
@dataclass(frozen=True, slots=True)
class DomainProduct:
    domain_product_id: str
    number: str
    name: str
    catalog_code: str | None
    hidden: bool
    kind: DomainProductKind = "micromarket"
    extra_catalog_codes: tuple[str, ...] = field(default_factory=tuple)
    legacy_ms_code: str | None = None
    unit: ProductUnit | None = None
    pack_size: Decimal | None = None


@beartype
def catalog_codes_of(product: DomainProduct) -> tuple[str, ...]:
    codes: list[str] = []
    if product.catalog_code:
        codes.append(product.catalog_code)
    for code in product.extra_catalog_codes:
        if code and code not in codes:
            codes.append(code)
    return tuple(codes)


@beartype
def packaging_is_form_ready(
    *,
    unit: ProductUnit | None,
    pack_size: Decimal | None,
) -> bool:
    return unit is not None and pack_size is not None and pack_size > 0


@beartype
@dataclass(frozen=True, slots=True)
class DomainProductImportRow:
    line_number: int
    name: str
    catalog_code: str


@beartype
@dataclass(frozen=True, slots=True)
class DomainProductImportFailure:
    line_number: int
    name: str
    message: str


@beartype
@dataclass(frozen=True, slots=True)
class DomainProductImportResult:
    created: int
    linked: int
    unchanged: int
    failures: tuple[DomainProductImportFailure, ...]
