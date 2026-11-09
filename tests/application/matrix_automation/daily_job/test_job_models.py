from __future__ import annotations

from decimal import Decimal

import pytest

from src.application.matrix_automation.job_models import MatrixDeployJob, MatrixDeployJobUnit


def test_terminal_job_requires_finished_at_and_status() -> None:
    job = MatrixDeployJob.started(job_id="job-1", started_at="2026-07-10T00:00:00+00:00")
    assert job.finished_at is None
    assert job.status is None
    assert (
        job.finalize(
            status="completed",
            finished_at="2026-07-10T00:01:00+00:00",
            units=(),
            blocked_matrices=(),
            auto_sync_disabled_matrices=0,
        ).status
        == "completed"
    )


def test_finalize_rejects_empty_finished_at() -> None:
    job = MatrixDeployJob.started(job_id="job-1", started_at="2026-07-10T00:00:00+00:00")
    with pytest.raises(ValueError, match="finished_at"):
        job.finalize(
            status="failed",
            finished_at="",
            units=(),
            blocked_matrices=(),
            auto_sync_disabled_matrices=0,
        )


def test_job_unit_allows_none_sku_stats_for_blocked() -> None:
    unit = MatrixDeployJobUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="skipped",
        deploy_reason="unknown_product_name",
        sku_stats=None,
        strong_price_increase_lines=(),
        product_swap_blocked_lines=(),
    )
    assert unit.sku_stats is None
    assert unit.strong_price_increase_lines == ()
    assert unit.product_swap_blocked_lines == ()


def test_sku_stats_counts_strong_price_increase_only_for_applied_lines() -> None:
    from src.application.matrix_automation.models import MatrixDeployPayloadLine, SkuStats
    from src.application.matrix_automation.sku_stats import sku_stats_from_lines

    lines = (
        MatrixDeployPayloadLine(
            line_number=1,
            product_code="A",
            product_name="Cola",
            deploy_price=Decimal("95.00"),
            capacity=5,
            outcome="applied",
            reason=None,
            strong_price_increase=True,
            baseline_price=Decimal("60.00"),
        ),
        MatrixDeployPayloadLine(
            line_number=2,
            product_code="B",
            product_name="Water",
            deploy_price=Decimal("40.00"),
            capacity=3,
            outcome="kept_previous",
            reason=None,
            strong_price_increase=False,
        ),
        MatrixDeployPayloadLine(
            line_number=3,
            product_code="C",
            product_name="Snack",
            deploy_price=Decimal("10.00"),
            capacity=2,
            outcome="product_swap_blocked",
            reason="stock_positive",
            strong_price_increase=False,
            desired_product="D",
        ),
    )
    assert sku_stats_from_lines(lines) == SkuStats(
        applied=1,
        kept_previous=1,
        skipped_no_baseline=0,
        strong_price_increase=1,
        blocked_empty=0,
        product_swap_blocked=1,
    )
