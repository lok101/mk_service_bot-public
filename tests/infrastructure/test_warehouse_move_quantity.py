from __future__ import annotations

from decimal import Decimal

import pytest

from src.domain.product_catalog import ProductSpec, ProductUnit, default_moysklad_quantity_factor
from src.infrastructure.integrations.moysklad.product_spec_resolver import (
    MappingProductSpecByCodeResolver,
)
from src.infrastructure.integrations.moysklad.warehouse_move_quantity import (
    MoySkladCatalogBaseQuantityResolver,
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


def _resolver() -> MoySkladCatalogBaseQuantityResolver:
    return MoySkladCatalogBaseQuantityResolver(
        product_resolver=MappingProductSpecByCodeResolver({"coffee": _coffee()}),
    )


def test_try_resolve_line_returns_primary_sku_and_quantity() -> None:
    """happy: known code → (primary_sku, base qty)."""
    assert _resolver().try_resolve_line(
        product_code="coffee",
        moysklad_quantity=Decimal("10"),
    ) == ("coffee", Decimal("10"))


def test_try_resolve_line_returns_none_for_unknown_code() -> None:
    """edge: miss catalog → None (не ValueError)."""
    assert (
        _resolver().try_resolve_line(
            product_code="kit-outside",
            moysklad_quantity=Decimal("1"),
        )
        is None
    )


def test_try_resolve_line_raises_for_empty_code() -> None:
    """error: empty code → ValueError (не truncate)."""
    with pytest.raises(ValueError, match="empty"):
        _resolver().try_resolve_line(
            product_code="  ",
            moysklad_quantity=Decimal("1"),
        )


def test_resolve_line_raises_when_try_resolve_line_returns_none() -> None:
    """compat: resolve_line при miss → ValueError."""
    with pytest.raises(ValueError, match="not found"):
        _resolver().resolve_line(
            product_code="kit-outside",
            moysklad_quantity=Decimal("1"),
        )
