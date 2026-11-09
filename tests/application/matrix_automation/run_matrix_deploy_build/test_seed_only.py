from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.deploy_reasons import BASELINE_ALREADY_PRESENT
from src.application.matrix_automation.models import MatrixParseState
from src.application.matrix_automation.run_matrix_deploy_build import (
    PurchaseFetchGlobalAbort,
    RunMatrixDeployBuild,
)

from .fakes import (
    _base_margin,
    _CountingPurchaseReader,
    _enabled_matrix,
    _FixedStockProvider,
    _KeyedSnapshotStore,
    _RecordingPurchaseReader,
    _snapshot_document,
    _SnapshotStoreWithUnits,
)


def test_seed_only_fetch_attributes_only_from_matrices_with_candidates() -> None:
    """happy: матрица A все со snapshot, B без — fetch только коды B."""
    store = _SnapshotStoreWithUnits(
        has_snapshot_for={("MatrixA", "1")},
    )
    reader = _RecordingPurchaseReader(prices={"PB": ("1.00", 1)})
    runner = RunMatrixDeployBuild(
        snapshot_store=store,
        purchase_reader=reader,
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=_base_margin(),
        product_multipliers={},
        seed_only=True,
    )
    state = MatrixParseState(
        enabled_matrices=(
            _enabled_matrix(name="MatrixA", machines=("1",), product="PA"),
            _enabled_matrix(name="MatrixB", machines=("2",), product="PB"),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = runner(state, job_id="job-seed")
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert len(reader.calls) == 1
    assert reader.calls[0] == frozenset({"PB"})
    assert "PA" not in reader.calls[0]


def test_seed_only_empty_candidates_skips_fetch_and_deploy_payloads() -> None:
    """edge: все units со snapshot → fetch_count=0, payloads пусты, skipped=baseline."""
    store = _SnapshotStoreWithUnits(has_snapshot_for={("Snacks", "512")})
    reader = _CountingPurchaseReader(prices={"P1": ("1.00", 1)})
    runner = RunMatrixDeployBuild(
        snapshot_store=store,
        purchase_reader=reader,
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=_base_margin(),
        product_multipliers={},
        seed_only=True,
    )
    state = MatrixParseState(
        enabled_matrices=(_enabled_matrix(name="Snacks", machines=("512",), product="P1"),),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = runner(state, job_id="job-seed")
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert reader.fetch_count == 0
    assert result.payloads == ()
    assert result.skipped_units[0].deploy_reason == BASELINE_ALREADY_PRESENT


def test_seed_only_call_argument_skips_fetch_and_deploy_payloads() -> None:
    """regression: RunMatrixDeployBuildPort принимает seed_only при вызове."""
    store = _SnapshotStoreWithUnits(has_snapshot_for={("Snacks", "512")})
    reader = _CountingPurchaseReader(prices={"P1": ("1.00", 1)})
    runner = RunMatrixDeployBuild(
        snapshot_store=store,
        purchase_reader=reader,
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=_base_margin(),
        product_multipliers={},
    )
    state = MatrixParseState(
        enabled_matrices=(_enabled_matrix(name="Snacks", machines=("512",), product="P1"),),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )

    result = runner(state, job_id="job-seed", seed_only=True)

    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert reader.fetch_count == 0
    assert result.payloads == ()
    assert result.skipped_units[0].deploy_reason == BASELINE_ALREADY_PRESENT


def test_seed_only_guard_fetch_scoped_to_candidate_matrices_only() -> None:
    """edge: seed_only + guard — union/prescan только матрицы с ≥1 кандидатом."""
    store = _KeyedSnapshotStore(
        {
            ("1", "MatrixA", 1): _snapshot_document(
                machine_code="1",
                logical_matrix_name="MatrixA",
                product_code="OLD",
            ),
        },
    )
    reader = _RecordingPurchaseReader(prices={"NEW": ("20", 10), "PB": ("1.00", 1)})
    runner = RunMatrixDeployBuild(
        snapshot_store=store,
        purchase_reader=reader,
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=_base_margin(),
        product_multipliers={"NEW": Decimal("1"), "PB": Decimal("1")},
        substitution_guard_enabled=True,
        stock_provider=_FixedStockProvider(0),
        seed_only=True,
    )
    state = MatrixParseState(
        enabled_matrices=(
            _enabled_matrix(name="MatrixA", machines=("1",), product="NEW"),
            _enabled_matrix(name="MatrixB", machines=("2",), product="PB"),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = runner(state, job_id="job-seed")
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert len(reader.calls) == 1
    assert reader.calls[0] == frozenset({"PB"})
    assert "OLD" not in reader.calls[0]
    assert "NEW" not in reader.calls[0]
