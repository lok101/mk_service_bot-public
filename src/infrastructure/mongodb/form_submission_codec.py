from __future__ import annotations

from decimal import Decimal
from typing import Any

from beartype import beartype

from src.domain.form_submission import FrozenInventoryLine, FrozenProductSpec
from src.domain.product_catalog import ProductUnit


@beartype
def serialize_product_unit(unit: ProductUnit) -> str:
    return unit.name.lower()


@beartype
def deserialize_product_unit(value: str) -> ProductUnit:
    normalized = value.strip().upper()
    try:
        return ProductUnit[normalized]
    except KeyError as error:
        raise ValueError(f"Unknown product unit: {value!r}") from error


@beartype
def serialize_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


@beartype
def deserialize_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


@beartype
def frozen_line_to_document(line: FrozenInventoryLine) -> dict[str, Any]:
    return {
        "form_title": line.form_title,
        "quantity": serialize_decimal(line.quantity),
        "product_spec": frozen_product_spec_to_document(line.product_spec),
    }


@beartype
def frozen_product_spec_to_document(spec: FrozenProductSpec) -> dict[str, Any]:
    return {
        "product_code": spec.product_code,
        "name": spec.name,
        "unit": serialize_product_unit(spec.unit),
        "pack_size": serialize_decimal(spec.pack_size),
        "moysklad_quantity_factor": serialize_decimal(spec.moysklad_quantity_factor),
    }


@beartype
def document_to_validated_lines(
    document: dict[str, Any],
) -> tuple[FrozenInventoryLine, ...]:
    raw_lines = document.get("validated_lines")
    if not isinstance(raw_lines, list):
        raise ValueError("Form submission validated_lines must be a list")

    lines: list[FrozenInventoryLine] = []
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            raise ValueError("Form submission validated line must be an object")
        lines.append(document_to_frozen_line(raw_line))
    return tuple(lines)


@beartype
def document_to_frozen_line(document: dict[str, Any]) -> FrozenInventoryLine:
    form_title = document.get("form_title")
    quantity = document.get("quantity")
    raw_spec = document.get("product_spec")
    if (
        not isinstance(form_title, str)
        or not isinstance(quantity, str)
        or not isinstance(raw_spec, dict)
    ):
        raise ValueError("Form submission validated line has invalid shape")

    return FrozenInventoryLine(
        form_title=form_title,
        product_spec=document_to_frozen_product_spec(raw_spec),
        quantity=deserialize_decimal(quantity) or Decimal("0"),
    )


@beartype
def document_to_frozen_product_spec(document: dict[str, Any]) -> FrozenProductSpec:
    product_code = document.get("product_code")
    name = document.get("name")
    unit = document.get("unit")
    pack_size = document.get("pack_size")
    moysklad_quantity_factor = document.get("moysklad_quantity_factor")
    if (
        not isinstance(product_code, str)
        or not isinstance(name, str)
        or not isinstance(unit, str)
        or not isinstance(moysklad_quantity_factor, str)
    ):
        raise ValueError("Form submission product_spec has invalid shape")

    resolved_pack_size: str | None
    if pack_size is None:
        resolved_pack_size = None
    elif isinstance(pack_size, str):
        resolved_pack_size = pack_size
    else:
        raise ValueError("Form submission product_spec pack_size must be a string or null")

    resolved_factor = deserialize_decimal(moysklad_quantity_factor)
    if resolved_factor is None:
        raise ValueError("Form submission product_spec moysklad_quantity_factor is required")

    return FrozenProductSpec(
        product_code=product_code,
        name=name,
        unit=deserialize_product_unit(unit),
        pack_size=deserialize_decimal(resolved_pack_size),
        moysklad_quantity_factor=resolved_factor,
    )
