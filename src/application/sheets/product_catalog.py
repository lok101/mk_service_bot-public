from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from beartype import beartype

from src.application.shared.product_title import product_name_for_lookup
from src.application.shared.sheet_rows import (
    cell_value,
    normalize_header_cells,
    row_has_values,
)
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)

PRODUCT_CATALOG_ID_COLUMN = "id"
PRODUCT_CATALOG_NAME_COLUMN = "имя"

__all__ = [
    "ParsedProductCatalog",
    "parse_product_catalog_sheet",
    "product_name_for_lookup",
]


@beartype
@dataclass(frozen=True, slots=True)
class ParsedProductCatalog:
    lookup: dict[str, ProductSpec]
    code_keys: frozenset[str]


@beartype
def parse_product_catalog_sheet(rows: list[list[str]]) -> ParsedProductCatalog:
    if not rows:
        raise ValueError("Product catalog sheet is empty")

    normalized_headers = normalize_header_cells(rows[0])
    try:
        id_index = normalized_headers.index(PRODUCT_CATALOG_ID_COLUMN)
        name_index = normalized_headers.index(PRODUCT_CATALOG_NAME_COLUMN)
    except ValueError as error:
        raise ValueError(
            "Product catalog sheet must contain ID and Имя columns",
        ) from error

    uom_index = normalized_headers.index("uom") if "uom" in normalized_headers else None
    pack_size_index = (
        normalized_headers.index("pack_size") if "pack_size" in normalized_headers else None
    )
    min_index = normalized_headers.index("min") if "min" in normalized_headers else None
    max_index = normalized_headers.index("max") if "max" in normalized_headers else None
    allow_fraction_index = (
        normalized_headers.index("allow_fraction")
        if "allow_fraction" in normalized_headers
        else None
    )
    ms_factor_index = (
        normalized_headers.index("ms_factor") if "ms_factor" in normalized_headers else None
    )
    aliases_index = normalized_headers.index("aliases") if "aliases" in normalized_headers else None
    aliases_id_index = (
        normalized_headers.index("aliases id") if "aliases id" in normalized_headers else None
    )

    lookup: dict[str, ProductSpec] = {}
    code_keys: set[str] = set()

    for row_number, row in enumerate(rows[1:], start=2):
        if not row_has_values(row):
            continue

        product_code = cell_value(row, id_index)
        product_name = cell_value(row, name_index)
        if not product_code or not product_name:
            continue

        unit_value = cell_value(row, uom_index) if uom_index is not None else ""
        unit = _parse_unit(unit_value) if unit_value else ProductUnit.GRAM

        pack_size_value = cell_value(row, pack_size_index) if pack_size_index is not None else ""
        pack_size = _parse_catalog_decimal(
            pack_size_value,
            field="pack_size",
            row_number=row_number,
            product_name=product_name,
        )

        min_value = cell_value(row, min_index) if min_index is not None else ""
        min_stock = _parse_catalog_decimal(
            min_value,
            field="min",
            row_number=row_number,
            product_name=product_name,
        )

        max_value = cell_value(row, max_index) if max_index is not None else ""
        max_stock = _parse_catalog_decimal(
            max_value,
            field="max",
            row_number=row_number,
            product_name=product_name,
        )
        _validate_stock_bounds(
            min_stock=min_stock,
            max_stock=max_stock,
            row_number=row_number,
            product_name=product_name,
        )

        allow_fraction_raw = (
            cell_value(row, allow_fraction_index) if allow_fraction_index is not None else ""
        )
        allow_fraction = allow_fraction_raw.strip().lower() in {"1", "true", "yes", "да"}

        ms_factor_value = cell_value(row, ms_factor_index) if ms_factor_index is not None else ""
        if ms_factor_value:
            moysklad_quantity_factor = _parse_required_catalog_decimal(
                ms_factor_value,
                field="ms_factor",
                row_number=row_number,
                product_name=product_name,
            )
        else:
            moysklad_quantity_factor = default_moysklad_quantity_factor(unit)
        _validate_moysklad_quantity_factor(
            moysklad_quantity_factor=moysklad_quantity_factor,
            row_number=row_number,
            product_name=product_name,
        )

        spec = ProductSpec(
            product_code=product_code,
            name=product_name,
            unit=unit,
            pack_size=pack_size,
            min_stock=min_stock,
            max_stock=max_stock,
            allow_fraction=allow_fraction,
            moysklad_quantity_factor=moysklad_quantity_factor,
        )

        aliases_value = cell_value(row, aliases_index) if aliases_index is not None else ""
        _register_catalog_lookup_key(
            lookup,
            _catalog_lookup_key(product_name),
            spec,
            row_number=row_number,
        )
        for alias in _parse_aliases(aliases_value):
            _register_catalog_lookup_key(
                lookup,
                _catalog_lookup_key(alias),
                spec,
                row_number=row_number,
            )
        primary_code_key = product_code.strip().casefold()
        _register_catalog_lookup_key(
            lookup,
            primary_code_key,
            spec,
            row_number=row_number,
        )
        code_keys.add(primary_code_key)
        aliases_id_value = cell_value(row, aliases_id_index) if aliases_id_index is not None else ""
        for alias_id in _parse_alias_ids(aliases_id_value):
            alias_code_key = alias_id.strip().casefold()
            _register_catalog_lookup_key(
                lookup,
                alias_code_key,
                spec,
                row_number=row_number,
            )
            code_keys.add(alias_code_key)

    if not lookup:
        raise ValueError("Product catalog sheet has no product rows")

    return ParsedProductCatalog(lookup=lookup, code_keys=frozenset(code_keys))


@beartype
def _catalog_lookup_key(name: str) -> str:
    return product_name_for_lookup(name).casefold()


@beartype
def _parse_alias_ids(value: str) -> tuple[str, ...]:
    return _parse_aliases(value)


@beartype
def _parse_aliases(value: str) -> tuple[str, ...]:
    normalized = value.strip()
    if not normalized:
        return ()

    aliases: list[str] = []
    for chunk in normalized.replace(";", ",").split(","):
        alias = chunk.strip()
        if alias:
            aliases.append(alias)
    return tuple(aliases)


@beartype
def _register_catalog_lookup_key(
    lookup: dict[str, ProductSpec],
    key: str,
    spec: ProductSpec,
    *,
    row_number: int,
) -> None:
    existing = lookup.get(key)
    if existing is not None and existing.product_code != spec.product_code:
        raise ValueError(
            f"Duplicate product name, alias, or alias id in catalog at row {row_number}: {key!r}",
        )
    lookup[key] = spec


@beartype
def _parse_unit(value: str) -> ProductUnit:
    normalized = value.strip().lower()
    if normalized in {"гр", "г", "gram", "g"}:
        return ProductUnit.GRAM
    if normalized in {"кг", "kg", "kilogram"}:
        return ProductUnit.KILOGRAM
    if normalized in {"мл", "ml"}:
        return ProductUnit.MILLILITER
    if normalized in {"шт", "pc", "piece"}:
        return ProductUnit.PIECE
    raise ValueError(f"Unknown product unit: {value!r}")


_OPTIONAL_DECIMAL_EMPTY = frozenset(
    {
        "",
        "-",
        "—",
        "–",
        "n/a",
        "#n/a",
        "нет",
        "null",
        "none",
    },
)


@beartype
def _normalize_decimal_text(value: str) -> str:
    text = value.replace("\u00a0", " ").strip()
    if text.lower() in _OPTIONAL_DECIMAL_EMPTY:
        return ""
    # RU-style thousands: "1 000" / "100 000"; decimal comma: "12,5"
    text = text.replace(" ", "")
    return text.replace(",", ".")


@beartype
def _parse_catalog_decimal(
    value: str,
    *,
    field: str,
    row_number: int,
    product_name: str,
    required: bool = False,
) -> Decimal | None:
    normalized = _normalize_decimal_text(value)
    if not normalized:
        if required:
            raise ValueError(
                f"Product catalog row {row_number} ({product_name!r}): "
                f"column {field!r} must be a number, got {value!r}",
            )
        return None

    try:
        parsed = Decimal(normalized)
    except InvalidOperation as error:
        raise ValueError(
            f"Product catalog row {row_number} ({product_name!r}): "
            f"invalid number in column {field!r}: {value!r}",
        ) from error
    if parsed < 0:
        raise ValueError(
            f"Product catalog row {row_number} ({product_name!r}): "
            f"column {field!r} must not be negative, got {value!r}",
        )
    return parsed


@beartype
def _parse_required_catalog_decimal(
    value: str,
    *,
    field: str,
    row_number: int,
    product_name: str,
) -> Decimal:
    parsed = _parse_catalog_decimal(
        value,
        field=field,
        row_number=row_number,
        product_name=product_name,
        required=True,
    )
    if parsed is None:
        raise ValueError(
            f"Product catalog row {row_number} ({product_name!r}): "
            f"column {field!r} must be a number, got {value!r}",
        )
    return parsed


@beartype
def _validate_stock_bounds(
    *,
    min_stock: Decimal | None,
    max_stock: Decimal | None,
    row_number: int,
    product_name: str,
) -> None:
    if min_stock is None or max_stock is None:
        return
    if min_stock > max_stock:
        raise ValueError(
            f"Product catalog row {row_number} ({product_name!r}): "
            "column 'min' must be less than or equal to column 'max'",
        )


@beartype
def _validate_moysklad_quantity_factor(
    *,
    moysklad_quantity_factor: Decimal,
    row_number: int,
    product_name: str,
) -> None:
    if moysklad_quantity_factor <= 0:
        raise ValueError(
            f"Product catalog row {row_number} ({product_name!r}): "
            "column 'ms_factor' must be greater than zero",
        )
