from __future__ import annotations

from src.application.matrix_automation.models import BlockedMatrixEntry, SkuStats
from src.infrastructure.matrix_automation.telegram_notifier import format_main_summary

from .fakes import _DELTA, _job, _unit


def test_completed_summary_has_required_counts_and_sku_line() -> None:
    job = _job(
        status="completed",
        auto_sync_disabled_matrices=4,
        units=(
            _unit(
                machine_code="512",
                sku_stats=SkuStats(
                    applied=10,
                    kept_previous=2,
                    skipped_no_baseline=1,
                    strong_price_increase=0,
                    blocked_empty=2,
                    product_swap_blocked=1,
                ),
            ),
            _unit(
                machine_code="100",
                deploy_status="failed",
                deploy_reason="upload_failed",
                sku_stats=SkuStats(applied=2),
            ),
            _unit(
                machine_code="200",
                deploy_status="skipped",
                deploy_reason="incomplete_matrix_no_snapshot",
                sku_stats=SkuStats(skipped_no_baseline=1),
            ),
        ),
        blocked_matrices=(
            BlockedMatrixEntry(
                logical_matrix_name="Blocked",
                deploy_reason="unknown_product_name",
                detail="x",
                products=(),
                machine_codes=("300",),
            ),
        ),
    )

    text = format_main_summary(job, global_abort_reason=None, max_price_delta_pct=_DELTA)

    assert text.startswith("Matrix deploy job completed")
    assert "Units: applied 1 / failed 1 / skipped 1" in text
    assert "Matrices auto-sync disabled: 4" in text
    assert "Blocked matrices: 1" in text
    assert (
        "SKU: applied 12 | kept_previous 2 | skipped_no_baseline 2"
        " | blocked_empty 2 | product_swap_blocked 1"
    ) in text
    assert "Товары с сильным повышением цены" not in text
    assert "Смена товара заблокирована" in text
    assert "Deploy failed:" in text
    assert "Snacks / 100: upload_failed" in text


def test_deploy_failed_block_renders_kit_machine_lookup_failed() -> None:
    job = _job(
        status="failed",
        units=(
            _unit(
                machine_code="512",
                deploy_status="failed",
                deploy_reason="kit_machine_lookup_failed",
                sku_stats=SkuStats(applied=0),
            ),
        ),
    )
    text = format_main_summary(job, global_abort_reason=None, max_price_delta_pct=_DELTA)
    assert "Deploy failed:" in text
    assert "Snacks / 512: kit_machine_lookup_failed" in text


def test_skipped_empty_scope_uses_units_zero_zero_zero_message() -> None:
    job = _job(status="skipped", auto_sync_disabled_matrices=3, units=())

    text = format_main_summary(job, global_abort_reason=None, max_price_delta_pct=_DELTA)

    assert "Matrix deploy job skipped" in text
    assert "Matrices auto-sync disabled: 3" in text
    assert "Units: 0/0/0" in text
    assert "нет enabled-матриц для deploy" in text
    assert "SKU:" not in text


def test_skipped_all_skipped_uses_k_and_kit_not_run_message() -> None:
    job = _job(
        status="skipped",
        auto_sync_disabled_matrices=1,
        units=(
            _unit(
                machine_code="512",
                deploy_status="skipped",
                deploy_reason="unknown_product_name",
                sku_stats=None,
            ),
            _unit(
                machine_code="100",
                deploy_status="skipped",
                deploy_reason="unknown_product_name",
                sku_stats=None,
            ),
        ),
        blocked_matrices=(
            BlockedMatrixEntry(
                logical_matrix_name="Snacks",
                deploy_reason="unknown_product_name",
                detail="x",
                products=(),
                machine_codes=("512", "100"),
            ),
        ),
    )

    text = format_main_summary(job, global_abort_reason=None, max_price_delta_pct=_DELTA)

    assert "Matrix deploy job skipped" in text
    assert "Units: 0/0/2" in text
    assert "Blocked matrices: 1" in text
    assert "Kit deploy не выполнялся" in text
    assert "SKU:" not in text


def test_global_abort_summary_omits_sku_and_deploy_blocks() -> None:
    job = _job(status="failed", auto_sync_disabled_matrices=0, units=())

    text = format_main_summary(
        job,
        global_abort_reason="sync_failed: sheet unavailable",
        max_price_delta_pct=_DELTA,
    )

    assert text == ("Matrix deploy job failed\nReason: sync_failed: sheet unavailable")
    assert "SKU:" not in text
    assert "Deploy failed:" not in text
    assert "Units:" not in text


def test_telegram_summary_has_no_price_stream_line() -> None:
    """happy: format_main_summary без price_stream_failed; нет строки Price stream."""
    import inspect

    assert "price_stream_failed" not in inspect.signature(format_main_summary).parameters
    job = _job(status="completed", units=(_unit(sku_stats=SkuStats(applied=1)),))
    text = format_main_summary(job, global_abort_reason=None, max_price_delta_pct=_DELTA)
    assert "Price stream" not in text
