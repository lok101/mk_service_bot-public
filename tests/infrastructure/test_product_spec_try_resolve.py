from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.reference_data.models import ReferenceDataSourceId
from src.application.reference_data.provider import ReferenceDataProvider
from src.domain.product_catalog import ProductSpec, ProductUnit, default_moysklad_quantity_factor
from src.infrastructure.integrations.google.sheets.product_catalog_source import (
    GoogleSheetsProductCatalogSource,
)
from src.infrastructure.integrations.google.sheets.product_code_resolver import (
    GoogleSheetsProductSpecByCodeResolver,
)
from src.infrastructure.integrations.moysklad.product_spec_resolver import (
    MappingProductSpecByCodeResolver,
)


def _coffee() -> ProductSpec:
    unit = ProductUnit.PIECE
    return ProductSpec(
        product_code="coffee",
        name="Coffee",
        unit=unit,
        pack_size=Decimal("1"),
        min_stock=None,
        max_stock=None,
        allow_fraction=False,
        moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
    )


def _mapping() -> MappingProductSpecByCodeResolver:
    return MappingProductSpecByCodeResolver(
        {"coffee": _coffee(), "coffee-alias": _coffee()},
    )


def _catalog_source(rows: list[list[str]]) -> GoogleSheetsProductCatalogSource:
    provider = ReferenceDataProvider()
    provider.apply_rows(ReferenceDataSourceId.PRODUCT_VITRINE, rows)
    return GoogleSheetsProductCatalogSource(provider=provider)


def test_try_resolve_by_code_returns_spec_for_known_code() -> None:
    """happy: ID / alias → ProductSpec."""
    resolver = _mapping()
    assert resolver.try_resolve_by_code("coffee").product_code == "coffee"
    assert resolver.try_resolve_by_code("COFFEE-ALIAS").product_code == "coffee"


def test_try_resolve_by_code_returns_none_for_unknown_code() -> None:
    """edge: непустой код вне map → None (не ValueError)."""
    assert _mapping().try_resolve_by_code("unknown-kit") is None


def test_try_resolve_by_code_raises_for_empty_code() -> None:
    """error: пустой / whitespace → ValueError."""
    resolver = _mapping()
    with pytest.raises(ValueError, match="empty"):
        resolver.try_resolve_by_code("")
    with pytest.raises(ValueError, match="empty"):
        resolver.try_resolve_by_code("   ")


def test_resolve_by_code_raises_when_try_resolve_returns_none() -> None:
    """happy/compat: resolve_by_code при miss → ValueError."""
    with pytest.raises(ValueError, match="not found"):
        _mapping().resolve_by_code("unknown-kit")


def test_sheets_try_resolve_by_code_returns_none_for_unknown() -> None:
    """edge: Sheets resolver — неизвестный код → None."""
    rows = [
        ["ID", "aliases id", "Имя", "uom"],
        ["16161616003327", "11344", "Кофе", "гр"],
    ]
    source = _catalog_source(rows)
    resolver = GoogleSheetsProductSpecByCodeResolver(catalog_source=source)
    assert resolver.try_resolve_by_code("missing-sku") is None


def test_sheets_try_resolve_by_code_raises_for_empty_code() -> None:
    """error: Sheets resolver — пустой код → ValueError."""
    rows = [
        ["ID", "aliases id", "Имя", "uom"],
        ["16161616003327", "11344", "Кофе", "гр"],
    ]
    source = _catalog_source(rows)
    resolver = GoogleSheetsProductSpecByCodeResolver(catalog_source=source)
    with pytest.raises(ValueError, match="empty"):
        resolver.try_resolve_by_code("")
    with pytest.raises(ValueError, match="empty"):
        resolver.try_resolve_by_code("   ")
