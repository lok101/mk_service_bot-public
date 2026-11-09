from __future__ import annotations

from decimal import Decimal

from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.build_deploy_payloads import BuildMatrixDeployPayloads
from src.application.matrix_automation.deploy_reasons import INCOMPLETE_MATRIX_NO_SNAPSHOT
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixParseState,
)

from .fakes import _builder, _PurchaseReader, _SnapshotStore


def test_blocked_matrix_emits_skipped_units_without_sku_stats() -> None:
    state = MatrixParseState(
        enabled_matrices=(),
        blocked_matrices=(
            BlockedMatrixEntry(
                logical_matrix_name="Snacks",
                deploy_reason="unknown_product_name",
                detail="unknown_product_name: X",
                products=(),
                machine_codes=("512", "513"),
            ),
        ),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = _builder()(state)
    assert result.payloads == ()
    assert len(result.skipped_units) == 2
    assert all(unit.sku_stats is None for unit in result.skipped_units)


def test_incomplete_unit_is_skipped_with_sku_stats() -> None:
    state = MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1.0"),
                cells=(MatrixCatalogCell(1, "Кола 0.5", "MS-1"),),
            ),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = BuildMatrixDeployPayloads(
        snapshot_store=_SnapshotStore(),
        purchase_reader=_PurchaseReader(prices={}),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=curved_margin_params(),
        product_multipliers={"MS-1": Decimal("1")},
        purchase_attributes={},
    )(state)
    assert result.payloads == ()
    assert len(result.skipped_units) == 1
    assert result.skipped_units[0].deploy_reason == INCOMPLETE_MATRIX_NO_SNAPSHOT
    assert result.skipped_units[0].sku_stats is not None


def test_invalid_volume_is_per_line_outcome() -> None:
    state = MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1.0"),
                cells=(MatrixCatalogCell(1, "Кола 0.5", "MS-1"),),
            ),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = BuildMatrixDeployPayloads(
        snapshot_store=_SnapshotStore(),
        purchase_reader=_PurchaseReader(prices={"MS-1": ("10.00", 0)}),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=curved_margin_params(),
        product_multipliers={"MS-1": Decimal("1")},
        purchase_attributes={"MS-1": ("10.00", 0)},
    )(state)
    assert len(result.skipped_units) == 1
    assert result.skipped_units[0].sku_stats is not None
    assert result.skipped_units[0].sku_stats.skipped_no_baseline == 1
