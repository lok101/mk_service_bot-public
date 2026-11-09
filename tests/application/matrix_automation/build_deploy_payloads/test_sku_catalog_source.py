from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.models import (
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixParseState,
)

from .fakes import _builder


def _state_one_line(product: str = "MS-1") -> MatrixParseState:
    return MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1.0"),
                cells=(MatrixCatalogCell(1, "Ignored Name", product),),
            ),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )


def test_build_uses_sku_catalog_capacity_multiplier_name() -> None:
    entry_15 = MatrixSkuCatalogEntry(
        product_code="MS-1",
        display_name="Panel Name",
        capacity=7,
        product_multiplier=Decimal("1.5"),
    )
    entry_10 = MatrixSkuCatalogEntry(
        product_code="MS-1",
        display_name="Panel Name",
        capacity=7,
        product_multiplier=Decimal("1"),
    )
    result_15 = _builder(
        prices={"MS-1": ("10.00", 999)},
        sku_catalog_by_code={"MS-1": entry_15},
    )(_state_one_line())
    result_10 = _builder(
        prices={"MS-1": ("10.00", 999)},
        sku_catalog_by_code={"MS-1": entry_10},
    )(_state_one_line())
    line_15 = result_15.payloads[0].lines[0]
    line_10 = result_10.payloads[0].lines[0]
    assert line_15.capacity == 7
    assert line_15.product_name == "Panel Name"
    assert line_15.deploy_price != line_10.deploy_price


def test_build_ignores_ms_volume_when_sku_catalog_on() -> None:
    entry = MatrixSkuCatalogEntry(
        product_code="MS-1",
        display_name="Panel Name",
        capacity=3,
        product_multiplier=Decimal("1"),
    )
    result = _builder(
        prices={"MS-1": ("10.00", 999)},
        sku_catalog_by_code={"MS-1": entry},
    )(_state_one_line())
    assert result.payloads[0].lines[0].capacity == 3


def test_build_blocks_non_ready_sku_line() -> None:
    entry = MatrixSkuCatalogEntry(
        product_code="MS-1",
        display_name="Panel Name",
        capacity=0,
        product_multiplier=Decimal("1"),
    )
    result = _builder(
        prices={"MS-1": ("10.00", 12)},
        sku_catalog_by_code={"MS-1": entry},
    )(_state_one_line())
    line = result.payloads[0].lines[0]
    assert line.outcome != "applied"


def test_build_blocks_missing_catalog_entry() -> None:
    """sku_catalog_by_code present but product code absent → line blocked, not applied."""
    result = _builder(
        prices={"MS-1": ("10.00", 12)},
        sku_catalog_by_code={},  # map present (flag-on), code missing
    )(_state_one_line())
    assert result.payloads
    line = result.payloads[0].lines[0]
    assert line.outcome != "applied"


def test_build_empty_catalog_does_not_global_abort() -> None:
    """Empty catalog map + line with product → blocked line; still returns payloads (no crash)."""
    result = _builder(
        prices={"MS-1": ("10.00", 12)},
        sku_catalog_by_code={},
    )(_state_one_line())
    assert result.payloads is not None
    assert len(result.payloads) >= 1
    assert result.payloads[0].lines[0].outcome != "applied"
