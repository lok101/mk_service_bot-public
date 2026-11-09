from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.form_submissions import ValidatedInventoryLine
from src.application.inventory_reconciliation.ms_registrar_ports import StockDocumentLine
from src.domain.inventory import InventoryPosition
from src.domain.product_catalog import ProductSpec
from src.domain.quantities import QuantityInputMode, packages_to_base_quantity


@beartype
@dataclass(frozen=True, slots=True)
class MoySkladLinePosition:
    product_code: str
    quantity: float | int
    price: int | None = None

    def __post_init__(self) -> None:
        if not self.product_code:
            raise ValueError("MoySkladLinePosition product_code must not be empty")


@beartype
def catalog_base_quantity(line: ValidatedInventoryLine, mode: QuantityInputMode) -> Decimal:
    """Quantity in catalog / form units (grams, milliliters, or pieces)."""
    if mode == QuantityInputMode.PACKAGE_COUNT:
        pack_size = line.product_spec.pack_size
        if pack_size is None or pack_size <= 0:
            raise ValueError(
                f"Pack size must be configured for product {line.product_spec.name!r}",
            )
        return packages_to_base_quantity(
            packages=line.quantity,
            pack_size=pack_size,
        )
    return line.quantity


@beartype
def to_moysklad_quantity(spec: ProductSpec, catalog_quantity: Decimal) -> Decimal:
    return catalog_quantity * spec.moysklad_quantity_factor


@beartype
def from_moysklad_quantity(spec: ProductSpec, moysklad_quantity: Decimal) -> Decimal:
    """Convert MoySklad API quantity to catalog base units (grams, milliliters, or pieces)."""
    return moysklad_quantity / spec.moysklad_quantity_factor


@beartype
def validated_lines_to_moysklad_positions(
    lines: list[ValidatedInventoryLine],
    *,
    mode: QuantityInputMode,
) -> list[MoySkladLinePosition]:
    positions: list[MoySkladLinePosition] = []
    for line in lines:
        catalog_quantity = catalog_base_quantity(line, mode)
        quantity = to_moysklad_quantity(line.product_spec, catalog_quantity)
        positions.append(
            MoySkladLinePosition(
                product_code=line.product_spec.product_code,
                quantity=_decimal_to_api_number(quantity),
            ),
        )
    return positions


@beartype
def stock_document_lines_to_moysklad_positions(
    lines: list[StockDocumentLine],
    *,
    resolve_spec: Callable[[str], ProductSpec],
) -> list[MoySkladLinePosition]:
    positions: list[MoySkladLinePosition] = []
    for line in lines:
        spec = resolve_spec(line.product_code)
        quantity = to_moysklad_quantity(spec, line.quantity)
        positions.append(
            MoySkladLinePosition(
                product_code=line.product_code,
                quantity=_decimal_to_api_number(quantity),
                price=line.price_kop,
            ),
        )
    return positions


@beartype
def stock_document_lines_to_as_sold_positions(
    lines: list[StockDocumentLine],
) -> list[MoySkladLinePosition]:
    """Daily demand positions: sales qty as MS quantity (no ProductSpec factor)."""
    return [
        MoySkladLinePosition(
            product_code=line.product_code,
            quantity=_decimal_to_api_number(line.quantity),
            price=line.price_kop,
        )
        for line in lines
    ]


@beartype
def moysklad_positions_to_inventory_positions(
    positions: list[MoySkladLinePosition],
) -> list[InventoryPosition]:
    return [
        InventoryPosition(product_code=position.product_code, quantity=position.quantity)
        for position in positions
    ]


@beartype
def parse_moysklad_quantity(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError(f"Unsupported MoySklad quantity value: {value!r}")


@beartype
def _decimal_to_api_number(quantity: Decimal) -> float | int:
    if quantity == quantity.to_integral_value():
        return int(quantity)
    return float(quantity)
