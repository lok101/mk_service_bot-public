from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.provider import ReferenceDataProvider
from src.application.sheets.product_catalog import ParsedProductCatalog
from src.domain.product_catalog import (
    ProductSpec,
    ProductUnit,
    default_moysklad_quantity_factor,
)
from src.infrastructure.integrations.google.sheets.product_catalog_source import (
    GoogleSheetsProductCatalogSource,
    code_index_from_catalog,
)
from src.infrastructure.integrations.google.sheets.product_code_resolver import (
    GoogleSheetsProductCodeResolver,
    GoogleSheetsProductSpecByCodeResolver,
)


def _spec(product_code: str) -> ProductSpec:
    unit = ProductUnit.PIECE
    return ProductSpec(
        product_code=product_code,
        name=product_code,
        unit=unit,
        pack_size=Decimal("1"),
        min_stock=None,
        max_stock=None,
        allow_fraction=False,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )


def test_code_index_from_catalog_maps_only_code_keys() -> None:
    cup = _spec("cup-1")
    coffee = _spec("coffee-1")
    catalog = ParsedProductCatalog(
        lookup={
            "cup": cup,
            "cup-1": cup,
            "coffee": coffee,
            "alias-9": coffee,
            "coffee-1": coffee,
        },
        code_keys=frozenset({"cup-1", "alias-9", "coffee-1"}),
    )

    index = code_index_from_catalog(catalog)

    assert set(index) == {"cup-1", "alias-9", "coffee-1"}
    assert "cup" not in index
    assert "coffee" not in index


def _catalog_source(rows: list[list[str]]) -> GoogleSheetsProductCatalogSource:
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.PRODUCT_VITRINE, rows)
    return GoogleSheetsProductCatalogSource(provider=provider)


def test_catalog_source_resolves_aliases_id_by_code() -> None:
    rows = [
        ["ID", "aliases id", "Имя", "uom"],
        ["16161616003327", "11344", "Кофе", "гр"],
    ]
    source = _catalog_source(rows)

    code_to_spec = source.get_code_to_spec()
    assert code_to_spec["11344"].name == "Кофе"
    assert code_to_spec["16161616003327"].product_code == "16161616003327"
    assert "кофе" not in code_to_spec

    resolver = GoogleSheetsProductSpecByCodeResolver(catalog_source=source)
    assert resolver.resolve_by_code("11344").name == "Кофе"

    name_resolver = GoogleSheetsProductCodeResolver(catalog_source=source)
    assert name_resolver.resolve_by_name("Кофе").product_code == "16161616003327"
    with pytest.raises(ValueError, match="Product spec not found for name '11344'"):
        name_resolver.resolve_by_name("11344")


def test_catalog_source_loads_sheet_once_for_name_and_code_indexes() -> None:
    rows = [
        ["id", "имя", "uom"],
        ["cup-1", "cup", "шт"],
    ]
    source = _catalog_source(rows)

    assert source.get_name_to_spec()["cup"].product_code == "cup-1"
    assert source.get_code_to_spec()["cup-1"].product_code == "cup-1"
    assert "cup" not in source.get_code_to_spec()


def test_degraded_catalog_returns_empty_indexes() -> None:
    source = GoogleSheetsProductCatalogSource(provider=ReferenceDataProvider())
    assert source.get_name_to_spec() == {}
    assert source.get_code_to_spec() == {}


def test_product_code_resolver_uses_vitrine_not_ms_name() -> None:
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_VITRINE,
        [["id", "имя"], ["c1", "FormName"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [["code", "name", "entity_kind"], ["c1", "MsName", "product"]],
    )
    source = GoogleSheetsProductCatalogSource(provider)
    name_keys = set(source.get_name_to_spec())
    assert "formname" in name_keys
    assert "msname" not in name_keys


def test_settlement_audit_product_name_uses_vitrine_not_ms() -> None:
    """Критерий приёмки #5: audit product name = ProductSpec.name с витрины."""
    provider = ReferenceDataProvider()
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_VITRINE,
        [["id", "имя"], ["c1", "VitrineName"]],
    )
    provider.apply_rows(
        ReferenceDataSourceId.PRODUCT_CATALOG,
        [["code", "name", "entity_kind"], ["c1", "MsName", "product"]],
    )
    source = GoogleSheetsProductCatalogSource(provider)
    spec = source.get_code_to_spec()["c1"]
    assert spec.name == "VitrineName"
