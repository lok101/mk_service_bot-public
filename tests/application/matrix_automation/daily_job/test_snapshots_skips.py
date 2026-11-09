from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.models import MatrixDeployPayload

from .fakes import (
    _build,
    _matrix,
    _payload,
    _result,
    _runner,
    _state,
)


def test_all_blocked_or_incomplete_units_are_skipped_not_failed() -> None:
    from src.application.matrix_automation.deploy_reasons import (
        INCOMPLETE_MATRIX_NO_SNAPSHOT,
        UNKNOWN_PRODUCT_NAME,
    )
    from src.application.matrix_automation.models import (
        BlockedMatrixEntry,
        MatrixDeploySkippedUnit,
        SkuStats,
    )

    skipped = (
        MatrixDeploySkippedUnit(
            logical_matrix_name="Blocked",
            machine_code="1",
            deploy_status="skipped",
            deploy_reason=UNKNOWN_PRODUCT_NAME,
            sku_stats=None,
        ),
        MatrixDeploySkippedUnit(
            logical_matrix_name="Incomplete",
            machine_code="2",
            deploy_status="skipped",
            deploy_reason=INCOMPLETE_MATRIX_NO_SNAPSHOT,
            sku_stats=SkuStats(skipped_no_baseline=1),
        ),
    )
    runner, _jobs, snapshots, _notifier, _deployer, _status = _runner(
        sync_result=_state(
            blocked_matrices=(
                BlockedMatrixEntry(
                    logical_matrix_name="Blocked",
                    deploy_reason=UNKNOWN_PRODUCT_NAME,
                    detail="x",
                    products=(),
                    machine_codes=("1",),
                ),
            ),
        ),
        build_result=_build(skipped_units=skipped),
        deploy_results=(),
    )
    job = runner.run()
    assert job.status == "skipped"
    assert [unit.deploy_status for unit in job.units] == ["skipped", "skipped"]
    assert snapshots.documents == []


def test_applied_unit_persists_snapshot_with_job_finished_at() -> None:
    from src.application.matrix_automation.models import MatrixDeployPayloadLine

    payload = MatrixDeployPayload(
        logical_matrix_name="Snacks",
        machine_code="512",
        matrix_multiplier="1.0",
        lines=(
            MatrixDeployPayloadLine(
                line_number=1,
                product_code="A",
                product_name="Cola",
                deploy_price=Decimal("50.00"),
                capacity=10,
                outcome="applied",
                reason=None,
                strong_price_increase=False,
                purchase_price=Decimal("20.00"),
                calculated_price=Decimal("50.00"),
            ),
        ),
    )
    runner, _jobs, snapshots, _notifier, _deployer, _status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("Snacks", "512"),)),
        build_result=_build(payloads=(payload,)),
        deploy_results=(_result("Snacks", "512", "applied", None),),
    )
    job = runner.run()
    assert job.finished_at == snapshots.documents[0].recorded_at
    assert snapshots.documents[0].job_id == job.job_id
    assert snapshots.documents[0].machine_code == "512"
    assert snapshots.documents[0].lines[0].product_code == "A"
    assert snapshots.documents[0].lines[0].deploy_price == "50.00"


def test_failed_deploy_does_not_persist_snapshot() -> None:
    runner, _jobs, snapshots, _notifier, _deployer, _status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("Snacks", "512"),)),
        build_result=_build(payloads=(_payload("Snacks", "512"),)),
        deploy_results=(_result("Snacks", "512", "failed", "upload_failed"),),
    )
    job = runner.run()
    assert job.status == "failed"
    assert job.units[0].deploy_status == "failed"
    assert job.units[0].deploy_reason == "upload_failed"
    assert snapshots.documents == []


def test_kit_machine_lookup_failed_propagates_to_job_unit() -> None:
    runner, _jobs, snapshots, _notifier, _deployer, _status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("Snacks", "512"),)),
        build_result=_build(payloads=(_payload("Snacks", "512"),)),
        deploy_results=(_result("Snacks", "512", "failed", "kit_machine_lookup_failed"),),
    )
    job = runner.run()
    assert job.status == "failed"
    assert job.units[0].deploy_status == "failed"
    assert job.units[0].deploy_reason == "kit_machine_lookup_failed"
    assert snapshots.documents == []


def test_partial_job_persists_only_applied_unit_snapshots() -> None:
    runner, _jobs, snapshots, _notifier, _deployer, _status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("A", "1"), _matrix("B", "2"))),
        build_result=_build(payloads=(_payload("A", "1"), _payload("B", "2"))),
        deploy_results=(
            _result("A", "1", "applied", None),
            _result("B", "2", "failed", "bind_failed"),
        ),
    )
    job = runner.run()
    assert job.status == "partial"
    assert len(snapshots.documents) == 1
    assert snapshots.documents[0].machine_code == "1"
    assert snapshots.documents[0].recorded_at == job.finished_at


def test_blocked_matrix_with_two_machines_finalizes_two_skipped_units_without_sku_stats() -> None:
    from src.application.matrix_automation.deploy_reasons import UNKNOWN_PRODUCT_NAME
    from src.application.matrix_automation.models import BlockedMatrixEntry, MatrixDeploySkippedUnit

    blocked = BlockedMatrixEntry(
        logical_matrix_name="Snacks",
        deploy_reason=UNKNOWN_PRODUCT_NAME,
        detail="unknown_product_name: X",
        products=(),
        machine_codes=("1", "2"),
    )
    skipped = (
        MatrixDeploySkippedUnit(
            logical_matrix_name="Snacks",
            machine_code="1",
            deploy_status="skipped",
            deploy_reason=UNKNOWN_PRODUCT_NAME,
            sku_stats=None,
        ),
        MatrixDeploySkippedUnit(
            logical_matrix_name="Snacks",
            machine_code="2",
            deploy_status="skipped",
            deploy_reason=UNKNOWN_PRODUCT_NAME,
            sku_stats=None,
        ),
    )
    runner, _jobs, snapshots, _notifier, deployer, _status = _runner(
        sync_result=_state(blocked_matrices=(blocked,), auto_sync_disabled_matrices=0),
        build_result=_build(skipped_units=skipped),
    )
    job = runner.run()
    assert job.status == "skipped"
    assert len(job.units) == 2
    assert len(job.blocked_matrices) == 1
    assert all(unit.sku_stats is None for unit in job.units)
    assert all(unit.strong_price_increase_lines == () for unit in job.units)
    assert all(unit.product_swap_blocked_lines == () for unit in job.units)
    assert deployer.calls == []
    assert snapshots.documents == []


def test_blocked_reason_clears_sku_stats_even_if_present() -> None:
    from src.application.matrix_automation.daily_job import job_unit_from_skipped
    from src.application.matrix_automation.deploy_reasons import UNKNOWN_PRODUCT_NAME
    from src.application.matrix_automation.models import MatrixDeploySkippedUnit, SkuStats

    unit = MatrixDeploySkippedUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="skipped",
        deploy_reason=UNKNOWN_PRODUCT_NAME,
        sku_stats=SkuStats(applied=1),
    )
    converted = job_unit_from_skipped(unit)
    assert converted.sku_stats is None
    assert converted.strong_price_increase_lines == ()
    assert converted.product_swap_blocked_lines == ()


def test_incomplete_skipped_unit_preserves_line_audit_from_pricing_lines() -> None:
    from src.application.matrix_automation.daily_job import job_unit_from_skipped
    from src.application.matrix_automation.deploy_reasons import INCOMPLETE_MATRIX_NO_SNAPSHOT
    from src.application.matrix_automation.models import (
        MatrixDeployPayloadLine,
        MatrixDeploySkippedUnit,
    )

    lines = (
        MatrixDeployPayloadLine(
            line_number=1,
            product_code="OLD",
            product_name="Cola",
            deploy_price=Decimal("95.00"),
            capacity=5,
            outcome="applied",
            reason="strong_price_increase_noted",
            strong_price_increase=True,
            baseline_price=Decimal("60.00"),
        ),
        MatrixDeployPayloadLine(
            line_number=2,
            product_code="CUR",
            product_name="Water",
            deploy_price=Decimal("10.00"),
            capacity=3,
            outcome="product_swap_blocked",
            reason="stock_positive",
            strong_price_increase=False,
            desired_product="NEW",
        ),
        MatrixDeployPayloadLine(
            line_number=3,
            product_code="Z",
            product_name="Snack",
            deploy_price=Decimal("20.00"),
            capacity=1,
            outcome="skipped_no_baseline",
            reason=None,
            strong_price_increase=False,
        ),
    )
    unit = MatrixDeploySkippedUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="skipped",
        deploy_reason=INCOMPLETE_MATRIX_NO_SNAPSHOT,
        sku_stats=None,
        lines=lines,
    )
    converted = job_unit_from_skipped(unit)
    assert converted.sku_stats is not None
    assert converted.sku_stats.applied == 1
    assert converted.sku_stats.strong_price_increase == 1
    assert converted.sku_stats.product_swap_blocked == 1
    assert converted.sku_stats.skipped_no_baseline == 1
    assert len(converted.strong_price_increase_lines) == 1
    assert converted.strong_price_increase_lines[0].baseline == "60.00"
    assert converted.strong_price_increase_lines[0].machine_code == "512"
    assert len(converted.product_swap_blocked_lines) == 1
    assert converted.product_swap_blocked_lines[0].desired_product == "NEW"


def test_strong_price_increase_without_baseline_does_not_diverge_stats_and_lines() -> None:
    from src.application.matrix_automation.daily_job import job_unit_from_payload_result
    from src.application.matrix_automation.models import MatrixDeployPayloadLine

    payload = MatrixDeployPayload(
        logical_matrix_name="Snacks",
        machine_code="512",
        matrix_multiplier="1.0",
        lines=(
            MatrixDeployPayloadLine(
                line_number=1,
                product_code="A",
                product_name="Cola",
                deploy_price=Decimal("95.00"),
                capacity=5,
                outcome="applied",
                reason=None,
                strong_price_increase=True,
                baseline_price=None,
            ),
        ),
    )
    unit = job_unit_from_payload_result(payload, _result("Snacks", "512", "applied", None))
    assert unit.sku_stats is not None
    assert len(unit.strong_price_increase_lines) == unit.sku_stats.strong_price_increase
    assert unit.sku_stats.strong_price_increase == 0
    assert unit.strong_price_increase_lines == ()


def test_incomplete_unit_keeps_sku_stats_and_line_audit_without_deploy() -> None:
    from src.application.matrix_automation.deploy_reasons import INCOMPLETE_MATRIX_NO_SNAPSHOT
    from src.application.matrix_automation.models import (
        MatrixDeployPayloadLine,
        MatrixDeploySkippedUnit,
    )

    incomplete_lines = (
        MatrixDeployPayloadLine(
            line_number=1,
            product_code="OLD",
            product_name="Cola",
            deploy_price=Decimal("95.00"),
            capacity=5,
            outcome="applied",
            reason="strong_price_increase_noted",
            strong_price_increase=True,
            baseline_price=Decimal("60.00"),
        ),
        MatrixDeployPayloadLine(
            line_number=2,
            product_code="CUR",
            product_name="Water",
            deploy_price=Decimal("10.00"),
            capacity=3,
            outcome="product_swap_blocked",
            reason="stock_positive",
            strong_price_increase=False,
            desired_product="NEW",
        ),
        MatrixDeployPayloadLine(
            line_number=3,
            product_code="Z",
            product_name="Snack",
            deploy_price=Decimal("20.00"),
            capacity=1,
            outcome="skipped_no_baseline",
            reason=None,
            strong_price_increase=False,
        ),
    )
    skipped = (
        MatrixDeploySkippedUnit(
            logical_matrix_name="Snacks",
            machine_code="512",
            deploy_status="skipped",
            deploy_reason=INCOMPLETE_MATRIX_NO_SNAPSHOT,
            sku_stats=None,
            lines=incomplete_lines,
        ),
    )
    payload_with_audit = MatrixDeployPayload(
        logical_matrix_name="Other",
        machine_code="100",
        matrix_multiplier="1.0",
        lines=(
            MatrixDeployPayloadLine(
                line_number=1,
                product_code="OLD",
                product_name="Cola",
                deploy_price=Decimal("95.00"),
                capacity=5,
                outcome="applied",
                reason="strong_price_increase_noted",
                strong_price_increase=True,
                baseline_price=Decimal("60.00"),
            ),
            MatrixDeployPayloadLine(
                line_number=2,
                product_code="CUR",
                product_name="Water",
                deploy_price=Decimal("10.00"),
                capacity=3,
                outcome="product_swap_blocked",
                reason="stock_positive",
                strong_price_increase=False,
                desired_product="NEW",
            ),
        ),
    )
    runner, _jobs, snapshots, _notifier, deployer, _status = _runner(
        sync_result=_state(enabled_matrices=(_matrix("Other", "100"),)),
        build_result=_build(payloads=(payload_with_audit,), skipped_units=skipped),
        deploy_results=(_result("Other", "100", "applied", None),),
    )
    job = runner.run()
    incomplete = next(unit for unit in job.units if unit.machine_code == "512")
    applied = next(unit for unit in job.units if unit.machine_code == "100")
    assert incomplete.deploy_status == "skipped"
    assert incomplete.deploy_reason == INCOMPLETE_MATRIX_NO_SNAPSHOT
    assert incomplete.sku_stats is not None
    assert incomplete.sku_stats.strong_price_increase == 1
    assert incomplete.sku_stats.product_swap_blocked == 1
    assert incomplete.sku_stats.skipped_no_baseline == 1
    assert len(incomplete.strong_price_increase_lines) == 1
    assert incomplete.strong_price_increase_lines[0].baseline == "60.00"
    assert len(incomplete.product_swap_blocked_lines) == 1
    assert incomplete.product_swap_blocked_lines[0].desired_product == "NEW"
    assert applied.sku_stats is not None
    assert applied.sku_stats.strong_price_increase == 1
    assert applied.sku_stats.product_swap_blocked == 1
    assert len(applied.strong_price_increase_lines) == 1
    assert applied.strong_price_increase_lines[0].baseline == "60.00"
    assert applied.strong_price_increase_lines[0].increase_pct == "58.3"
    assert len(applied.product_swap_blocked_lines) == 1
    assert applied.product_swap_blocked_lines[0].desired_product == "NEW"
    assert len(deployer.calls) == 1
    assert len(deployer.calls[0]) == 1
    assert snapshots.documents  # applied unit still persists snapshot
    assert all(doc.machine_code != "512" for doc in snapshots.documents)


def test_finalize_copies_blocked_matrices_and_disabled_count_from_same_parse_state() -> None:
    from src.application.matrix_automation.deploy_reasons import UNKNOWN_PRODUCT_NAME
    from src.application.matrix_automation.models import BlockedMatrixEntry

    blocked = (
        BlockedMatrixEntry(
            logical_matrix_name="Snacks",
            deploy_reason=UNKNOWN_PRODUCT_NAME,
            detail="x",
            products=(),
            machine_codes=("512",),
        ),
    )
    runner, _jobs, _snapshots, _notifier, _deployer, _status = _runner(
        sync_result=_state(blocked_matrices=blocked, auto_sync_disabled_matrices=2),
        build_result=_build(),
    )
    job = runner.run()
    assert job.blocked_matrices == blocked
    assert len(job.blocked_matrices) == 1
    assert job.auto_sync_disabled_matrices == 2
    assert job.status == "skipped"
