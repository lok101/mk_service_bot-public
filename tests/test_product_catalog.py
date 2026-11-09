from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.sheets.product_catalog import (
    parse_product_catalog_sheet,
    product_name_for_lookup,
)
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)


@pytest.fixture
def catalog_rows() -> list[list[str]]:
    return [
        ["ID", "Имя", "uom", "aliases"],
        ["16161616003332", "Вода", "мл", ""],
        ["16161616003327", "Кофе", "гр", ""],
        ["16161616003329", "Раф", "гр", "мокко"],
        ["16161616003316", "Стакан", "шт", ""],
    ]


def test_product_name_for_lookup_strips_icon_prefix() -> None:
    assert product_name_for_lookup("🟧 | Концентрат") == "Концентрат"


def test_product_name_for_lookup_returns_name_without_pipe_unchanged() -> None:
    assert product_name_for_lookup("  Кофе  ") == "Кофе"


def test_parse_product_catalog_sheet_resolves_icon_prefixed_names() -> None:
    rows = [
        ["ID", "Имя", "uom", "aliases"],
        ["1", "🟧 | Концентрат", "гр", ""],
    ]

    specs = parse_product_catalog_sheet(rows).lookup

    assert specs["концентрат"].product_code == "1"
    assert specs["концентрат"].name == "🟧 | Концентрат"


def test_parse_product_catalog_sheet_resolves_by_product_code_id(
    catalog_rows: list[list[str]],
) -> None:
    specs = parse_product_catalog_sheet(catalog_rows).lookup

    cup = specs["16161616003316"]
    assert cup.product_code == "16161616003316"
    assert cup.name == "Стакан"
    assert specs["16161616003316"] is specs["стакан"]


def test_parse_product_catalog_sheet_maps_products(
    catalog_rows: list[list[str]],
) -> None:
    specs = parse_product_catalog_sheet(catalog_rows).lookup

    assert {"вода", "кофе", "раф", "стакан", "мокко"} <= set(specs.keys())
    assert specs["вода"].product_code == "16161616003332"
    assert specs["кофе"].product_code == "16161616003327"
    assert specs["раф"].product_code == "16161616003329"
    assert specs["стакан"].product_code == "16161616003316"


def test_parse_product_catalog_sheet_parses_units(
    catalog_rows: list[list[str]],
) -> None:
    specs = parse_product_catalog_sheet(catalog_rows).lookup

    assert specs["вода"].unit == ProductUnit.MILLILITER
    assert specs["кофе"].unit == ProductUnit.GRAM
    assert specs["стакан"].unit == ProductUnit.PIECE


def test_parse_product_catalog_sheet_resolves_aliases(catalog_rows: list[list[str]]) -> None:
    specs = parse_product_catalog_sheet(catalog_rows).lookup

    assert specs["мокко"].product_code == specs["раф"].product_code
    assert specs["мокко"].name == "Раф"


def test_parse_product_catalog_sheet_parses_multiple_aliases() -> None:
    rows = [
        ["ID", "Имя", "uom", "aliases"],
        ["1", "Кофе", "гр", "эспрессо, зерновой"],
    ]

    specs = parse_product_catalog_sheet(rows).lookup

    assert specs["эспрессо"].name == "Кофе"
    assert specs["зерновой"].name == "Кофе"


def test_parse_product_catalog_sheet_resolves_by_aliases_id() -> None:
    rows = [
        ["ID", "aliases id", "Имя", "uom", "aliases"],
        ["16161616003327", "11344", "Кофе", "гр", ""],
    ]

    specs = parse_product_catalog_sheet(rows).lookup

    coffee = specs["11344"]
    assert coffee.name == "Кофе"
    assert coffee.product_code == "16161616003327"
    assert specs["16161616003327"] is coffee
    assert specs["кофе"] is coffee

    catalog = parse_product_catalog_sheet(rows)
    assert catalog.code_keys == frozenset({"16161616003327", "11344"})


def test_parse_product_catalog_sheet_parses_multiple_aliases_id() -> None:
    rows = [
        ["ID", "aliases id", "Имя", "uom"],
        ["16161616003327", "11344, 11345", "Кофе", "гр"],
    ]

    specs = parse_product_catalog_sheet(rows).lookup

    assert specs["11344"].product_code == "16161616003327"
    assert specs["11345"].product_code == "16161616003327"


def test_parse_product_catalog_sheet_rejects_duplicate_aliases_id() -> None:
    rows = [
        ["ID", "aliases id", "Имя", "uom"],
        ["16161616003316", "", "Стакан", "шт"],
        ["16161616003327", "11344", "Кофе", "гр"],
        ["16161616003329", "11344", "Раф", "гр"],
    ]

    with pytest.raises(ValueError, match="Duplicate product name, alias, or alias id"):
        parse_product_catalog_sheet(rows)


def test_parse_product_catalog_sheet_rejects_aliases_id_matching_other_primary_id() -> None:
    rows = [
        ["ID", "aliases id", "Имя", "uom"],
        ["16161616003316", "", "Стакан", "шт"],
        ["16161616003327", "16161616003316", "Кофе", "гр"],
    ]

    with pytest.raises(ValueError, match="Duplicate product name, alias, or alias id"):
        parse_product_catalog_sheet(rows)


def test_parse_product_catalog_sheet_rejects_duplicate_id_key() -> None:
    rows = [
        ["ID", "Имя", "uom", "aliases"],
        ["16161616003316", "Стакан", "шт", ""],
        ["16161616003327", "Кофе", "гр", "16161616003316"],
    ]

    with pytest.raises(ValueError, match="Duplicate product name, alias, or alias id"):
        parse_product_catalog_sheet(rows)


def test_parse_product_catalog_sheet_raises_on_duplicate_names() -> None:
    rows = [
        ["ID", "Имя", "uom", "aliases"],
        ["1", "Кофе", "гр", ""],
        ["2", "Кофе", "гр", ""],
    ]

    with pytest.raises(ValueError, match="Duplicate product name, alias, or alias id"):
        parse_product_catalog_sheet(rows)


def test_parse_product_catalog_sheet_raises_on_duplicate_alias_across_products() -> None:
    rows = [
        ["ID", "Имя", "uom", "aliases"],
        ["1", "Кофе", "гр", "латте"],
        ["2", "Чай", "гр", "латте"],
    ]

    with pytest.raises(ValueError, match="Duplicate product name, alias, or alias id"):
        parse_product_catalog_sheet(rows)


def test_parse_product_catalog_sheet_raises_on_missing_columns() -> None:
    with pytest.raises(ValueError, match="ID and Имя columns"):
        parse_product_catalog_sheet([["code", "title"]])


def test_parse_product_catalog_sheet_raises_on_empty_sheet() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_product_catalog_sheet([])


def test_parse_product_catalog_sheet_builds_product_spec(
    catalog_rows: list[list[str]],
) -> None:
    specs = parse_product_catalog_sheet(catalog_rows).lookup

    coffee = specs["кофе"]
    assert isinstance(coffee, ProductSpec)
    assert coffee.product_code == "16161616003327"
    assert coffee.unit == ProductUnit.GRAM
    assert coffee.moysklad_quantity_factor == default_moysklad_quantity_factor(ProductUnit.GRAM)


def test_parse_product_catalog_sheet_parses_spaced_thousands_in_min_max() -> None:
    rows = [
        ["ID", "Имя", "uom", "min", "max"],
        ["1", "Кофе", "гр", "100 000", "200 000"],
    ]

    specs = parse_product_catalog_sheet(rows).lookup

    assert specs["кофе"].min_stock == Decimal("100000")
    assert specs["кофе"].max_stock == Decimal("200000")


def test_parse_product_catalog_sheet_treats_dash_as_empty_min() -> None:
    rows = [
        ["ID", "Имя", "uom", "min"],
        ["1", "Кофе", "гр", "—"],
    ]

    specs = parse_product_catalog_sheet(rows).lookup

    assert specs["кофе"].min_stock is None


def test_parse_product_catalog_sheet_parses_kilogram_uom() -> None:
    rows = [
        ["ID", "Имя", "uom", "pack_size", "min", "max"],
        ["16161616003325", "Сахар", "кг", "1", "1", "20"],
    ]

    specs = parse_product_catalog_sheet(rows).lookup

    sugar = specs["сахар"]
    assert sugar.name == "Сахар"
    assert sugar.unit == ProductUnit.KILOGRAM
    assert sugar.pack_size == Decimal("1")
    assert sugar.moysklad_quantity_factor == Decimal("1")


def test_parse_product_catalog_sheet_reads_ms_factor_override() -> None:
    rows = [
        ["ID", "Имя", "uom", "ms_factor"],
        ["1", "Кофе", "гр", "1"],
    ]

    specs = parse_product_catalog_sheet(rows).lookup

    assert specs["кофе"].moysklad_quantity_factor == Decimal("1")


def test_parse_product_catalog_sheet_rejects_negative_decimal_values() -> None:
    rows = [
        ["ID", "Имя", "uom", "min"],
        ["1", "Кофе", "гр", "-1"],
    ]

    with pytest.raises(ValueError, match="must not be negative"):
        parse_product_catalog_sheet(rows)


def test_parse_product_catalog_sheet_rejects_non_positive_ms_factor() -> None:
    rows = [
        ["ID", "Имя", "uom", "ms_factor"],
        ["1", "Кофе", "гр", "0"],
    ]

    with pytest.raises(ValueError, match="ms_factor"):
        parse_product_catalog_sheet(rows)


def test_parse_product_catalog_sheet_rejects_min_greater_than_max() -> None:
    rows = [
        ["ID", "Имя", "uom", "min", "max"],
        ["1", "Кофе", "гр", "10", "5"],
    ]

    with pytest.raises(ValueError, match="less than or equal to"):
        parse_product_catalog_sheet(rows)
