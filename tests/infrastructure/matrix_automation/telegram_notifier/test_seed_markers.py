from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.job_models import StrongPriceIncreaseLine
from src.application.matrix_automation.models import BlockedMatrixEntry, SkuStats
from src.infrastructure.matrix_automation.telegram_notifier import (
    format_blocked_matrices_message,
    format_main_summary,
    kept_alert_text,
)

from .fakes import _job, _unit


def test_seed_completed_summary_first_line_has_seed_marker() -> None:
    job = _job(status="completed", trigger="seed", units=(_unit(sku_stats=SkuStats(applied=1)),))
    text = format_main_summary(job, global_abort_reason=None)
    assert text.splitlines()[0] == "Matrix deploy job (seed) completed"


def test_seed_skipped_summary_first_line_has_seed_marker() -> None:
    job = _job(status="skipped", trigger="seed")
    text = format_main_summary(job, global_abort_reason=None)
    assert text.splitlines()[0] == "Matrix deploy job (seed) skipped"


def test_seed_abort_summary_first_line_has_seed_marker() -> None:
    job = _job(status="failed", trigger="seed")
    text = format_main_summary(job, global_abort_reason="sheets_sync_failed")
    assert text.splitlines()[0] == "Matrix deploy job (seed) failed"
    assert "Reason: sheets_sync_failed" in text


def test_cron_completed_summary_unchanged() -> None:
    job = _job(status="completed", trigger="cron", units=(_unit(sku_stats=SkuStats(applied=1)),))
    text = format_main_summary(job, global_abort_reason=None)
    assert text.splitlines()[0] == "Matrix deploy job completed"


def test_seed_blocked_matrices_message_has_no_seed_marker() -> None:
    job = _job(
        status="partial",
        trigger="seed",
        blocked_matrices=(
            BlockedMatrixEntry(
                logical_matrix_name="Bad",
                deploy_reason="unknown_product_name",
                detail="x",
                products=(),
                machine_codes=("512",),
            ),
        ),
    )
    text = format_blocked_matrices_message(job)
    assert text is not None
    assert "(seed)" not in text
    assert text.splitlines()[0].startswith("Matrix deploy: blocked matrices")


def test_seed_kept_alert_has_no_seed_marker() -> None:
    job = _job(
        status="completed",
        trigger="seed",
        units=(
            _unit(
                sku_stats=SkuStats(kept_previous=3, strong_price_increase=1),
                strong_lines=(
                    StrongPriceIncreaseLine(
                        machine_code="512",
                        line_number=1,
                        product_code="P1",
                        baseline="10",
                        deploy_price="20",
                        increase_pct="100",
                    ),
                ),
            ),
        ),
    )
    text = kept_alert_text(job, Decimal("10"))
    assert text is not None
    assert "(seed)" not in text
