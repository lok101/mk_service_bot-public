from __future__ import annotations

import logging
from decimal import Decimal

from src.application.technician_warehouse.observe_loading import _normalize_loading_lines
from src.domain.form_submission import FrozenInventoryLine, FrozenProductSpec
from src.domain.product_catalog import ProductUnit, default_moysklad_quantity_factor


def _line(*, pack_size: str | None, packages: str = "2") -> FrozenInventoryLine:
    unit = ProductUnit.GRAM
    return FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code="coffee",
            name="Кофе",
            unit=unit,
            pack_size=None if pack_size is None else Decimal(pack_size),
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        ),
        quantity=Decimal(packages),
    )


def test_normalize_skips_missing_pack_size_with_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        result = _normalize_loading_lines((_line(pack_size=None), _line(pack_size="1000")))
    assert len(result) == 1
    assert result[0].sku == "coffee"
    assert any("pack_size" in record.message for record in caplog.records)


def test_normalize_skips_non_positive_quantity_without_pack_size_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        result = _normalize_loading_lines((_line(pack_size="1000", packages="0"),))
    assert result == ()
    assert not any("pack_size" in record.message for record in caplog.records)
