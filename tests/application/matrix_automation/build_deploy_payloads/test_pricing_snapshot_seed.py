from __future__ import annotations

from decimal import Decimal

from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.build_deploy_payloads import BuildMatrixDeployPayloads
from src.application.matrix_automation.deploy_reasons import (
    BASELINE_ALREADY_PRESENT,
    UNKNOWN_PRODUCT_NAME,
)
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixParseState,
    PriceSnapshotDocument,
    SnapshotLineRecord,
)

from .fakes import (
    _base_margin,
    _builder,
    _enabled_matrix,
    _PurchaseReader,
    _SnapshotStore,
    _SnapshotStoreWithUnits,
    _UnusedPurchaseReader,
)


def test_strong_price_increase_line_sets_baseline_price_from_snapshot() -> None:
    from src.application.matrix_automation.sku_stats import sku_stats_from_lines

    snapshot = PriceSnapshotDocument(
        job_id="job-1",
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at="2026-07-08T10:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code="MS-1",
                product_name="Кола 0.5",
                capacity=12,
                purchase_price="10.00",
                calculated_price="60.00",
                deploy_price="60.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )
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
    # purchase=80 → sell=100; baseline=60 → increase ≈ 66.7% > 30%
    result = _builder(
        store=_SnapshotStore([snapshot]),
        prices={"MS-1": ("80.00", 12)},
    )(state)
    assert len(result.payloads) == 1
    line = result.payloads[0].lines[0]
    assert line.outcome == "applied"
    assert line.strong_price_increase is True
    assert line.baseline_price == Decimal("60.00")
    stats = sku_stats_from_lines(result.payloads[0].lines)
    assert stats.strong_price_increase == 1


def test_kept_previous_carries_snapshot_product_name_and_capacity() -> None:
    snapshot = PriceSnapshotDocument(
        job_id="job-1",
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at="2026-07-08T10:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code="MS-1",
                product_name="Old Cola",
                capacity=8,
                purchase_price="10.00",
                calculated_price="100.00",
                deploy_price="100.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )
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
    result = _builder(store=_SnapshotStore([snapshot]))(state)
    line = result.payloads[0].lines[0]
    assert line.outcome == "kept_previous"
    assert line.product_name == "Old Cola"
    assert line.capacity == 8
    assert line.deploy_price == Decimal("100.00")


def test_is_first_run_is_per_unit_when_partial_snapshot_has_other_line() -> None:
    older_line_2 = PriceSnapshotDocument(
        job_id="job-0",
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at="2026-07-08T09:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=2,
                product_code="MS-2",
                product_name="Water",
                capacity=10,
                purchase_price="10.00",
                calculated_price="100.00",
                deploy_price="100.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )
    newer_line_1 = PriceSnapshotDocument(
        job_id="job-1",
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at="2026-07-08T11:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code="MS-1",
                product_name="Кола 0.5",
                capacity=12,
                purchase_price="10.00",
                calculated_price="30.00",
                deploy_price="30.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )
    state = MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1.0"),
                cells=(MatrixCatalogCell(2, "Water", "MS-2"),),
            ),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = BuildMatrixDeployPayloads(
        snapshot_store=_SnapshotStore([newer_line_1, older_line_2]),
        purchase_reader=_PurchaseReader(prices={"MS-2": ("10.00", 10)}),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=curved_margin_params(),
        product_multipliers={"MS-2": Decimal("1")},
        purchase_attributes={"MS-2": ("10.00", 10)},
    )(state)
    line = result.payloads[0].lines[0]
    assert line.outcome == "kept_previous"
    assert line.deploy_price == Decimal("100.00")


def test_seed_only_skips_unit_with_snapshot_before_pricing() -> None:
    """happy: seed_only + машина со snapshot → baseline_already_present, sku_stats is None."""
    store = _SnapshotStoreWithUnits(has_snapshot_for={("Snacks", "512")})
    builder = BuildMatrixDeployPayloads(
        snapshot_store=store,
        purchase_reader=_UnusedPurchaseReader(),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=_base_margin(),
        product_multipliers={},
        purchase_attributes={"P1": ("10.00", 5)},
        seed_only=True,
        job_id="job-seed",
    )
    state = MatrixParseState(
        enabled_matrices=(_enabled_matrix(name="Snacks", machines=("512", "100"), product="P1"),),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = builder(state)
    skipped_512 = next(u for u in result.skipped_units if u.machine_code == "512")
    assert skipped_512.deploy_reason == BASELINE_ALREADY_PRESENT
    assert skipped_512.sku_stats is None
    assert not any(
        u.machine_code == "100" and u.deploy_reason == BASELINE_ALREADY_PRESENT
        for u in result.skipped_units
    )
    assert len(result.payloads) == 1
    assert result.payloads[0].machine_code == "100"


def test_seed_only_blocked_reason_wins_over_baseline_skip() -> None:
    """edge: blocked matrix + snapshot на той же machine → deploy_reason blocked, не baseline."""
    store = _SnapshotStoreWithUnits(has_snapshot_for={("Blocked", "512")})
    builder = BuildMatrixDeployPayloads(
        snapshot_store=store,
        purchase_reader=_UnusedPurchaseReader(),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=_base_margin(),
        product_multipliers={},
        purchase_attributes={},
        seed_only=True,
    )
    blocked = BlockedMatrixEntry(
        logical_matrix_name="Blocked",
        deploy_reason=UNKNOWN_PRODUCT_NAME,
        detail="unknown",
        products=(),
        machine_codes=("512",),
    )
    state = MatrixParseState(
        enabled_matrices=(_enabled_matrix(name="Blocked", machines=("512",), product="P1"),),
        blocked_matrices=(blocked,),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = builder(state)
    assert len(result.payloads) == 0
    unit = result.skipped_units[0]
    assert unit.deploy_reason == UNKNOWN_PRODUCT_NAME
    assert unit.deploy_reason != BASELINE_ALREADY_PRESENT
