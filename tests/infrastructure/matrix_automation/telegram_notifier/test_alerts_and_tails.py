from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.job_models import (
    ProductSwapBlockedLine,
    StrongPriceIncreaseLine,
)
from src.application.matrix_automation.models import BlockedMatrixEntry, SkuStats
from src.infrastructure.matrix_automation.telegram_notifier import (
    format_blocked_matrices_message,
    format_main_summary,
    kept_alert_text,
)

from .fakes import _DELTA, _job, _unit


def test_strong_increase_lines_sort_descending_pct_then_machine_and_line() -> None:
    job = _job(
        status="completed",
        units=(
            _unit(
                machine_code="512",
                sku_stats=SkuStats(applied=3, strong_price_increase=3),
                strong_lines=(
                    StrongPriceIncreaseLine(
                        machine_code="512",
                        line_number=2,
                        product_code="A",
                        baseline="10.00",
                        deploy_price="20.00",
                        increase_pct="50.0",
                    ),
                    StrongPriceIncreaseLine(
                        machine_code="100",
                        line_number=1,
                        product_code="B",
                        baseline="10.00",
                        deploy_price="20.00",
                        increase_pct="50.0",
                    ),
                    StrongPriceIncreaseLine(
                        machine_code="512",
                        line_number=1,
                        product_code="C",
                        baseline="10.00",
                        deploy_price="30.00",
                        increase_pct="80.0",
                    ),
                ),
            ),
        ),
    )

    text = format_main_summary(job, global_abort_reason=None, max_price_delta_pct=_DELTA)
    strong_section = text.split("Товары с сильным повышением цены (> 30%): 3\n", 1)[1]
    bullet_lines = [line for line in strong_section.splitlines() if line.startswith("  • ")]
    assert bullet_lines == [
        "  • 512 L1 C: 10.00 → 30.00 (+80.0%)",
        "  • 100 L1 B: 10.00 → 20.00 (+50.0%)",
        "  • 512 L2 A: 10.00 → 20.00 (+50.0%)",
    ]


def test_deploy_failures_and_blocked_matrices_have_top_ten_tail() -> None:
    failed_units = tuple(
        _unit(
            logical_matrix_name=f"M{index:02d}",
            machine_code=str(100 + index),
            deploy_status="failed",
            deploy_reason="upload_failed",
            sku_stats=SkuStats(applied=1),
        )
        for index in range(1, 13)
    )
    blocked = tuple(
        BlockedMatrixEntry(
            logical_matrix_name=f"B{index:02d}",
            deploy_reason="invalid_matrix_header",
            detail="invalid_matrix_header: no_machines",
            products=(),
            machine_codes=(),
        )
        for index in range(1, 13)
    )
    job = _job(status="partial", units=failed_units, blocked_matrices=blocked)

    main = format_main_summary(job, global_abort_reason=None, max_price_delta_pct=_DELTA)
    assert "… и ещё 2 аппарат(ов)" in main
    assert main.count("upload_failed") == 10

    blocked_text = format_blocked_matrices_message(job)
    assert blocked_text is not None
    assert "Matrix deploy: blocked matrices (12)" in blocked_text
    assert "… и ещё 2 матриц(ы)" in blocked_text
    assert blocked_text.count("Reason: invalid_matrix_header") == 10


def test_blocked_message_uses_human_description_and_unknown_product_marker() -> None:
    from src.application.matrix_automation.models import BlockedProductRef

    job = _job(
        status="skipped",
        units=(
            _unit(
                deploy_status="skipped",
                deploy_reason="unknown_product_name",
                sku_stats=None,
            ),
        ),
        blocked_matrices=(
            BlockedMatrixEntry(
                logical_matrix_name="Snacks",
                deploy_reason="unknown_product_name",
                detail="unknown_product_name: Cola",
                products=(BlockedProductRef(product_name="Cola", product_code=None),),
                machine_codes=("512",),
            ),
            BlockedMatrixEntry(
                logical_matrix_name="Other",
                deploy_reason="invalid_matrix_header",
                detail="invalid_matrix_header: duplicate_machine_code: 100",
                products=(),
                machine_codes=("100",),
            ),
        ),
    )

    text = format_blocked_matrices_message(job)
    assert text is not None
    assert "Имя товара не найдено в листе „Товары“" in text
    assert "Products: Cola (unknown)" in text
    assert "В шапке матрицы дублируется код аппарата" in text
    other_block = text.split("• Other", 1)[1]
    assert "Products:" not in other_block


def test_kept_alert_is_strictly_greater_than_threshold_and_excludes_be_and_p() -> None:
    # A=5, Bk=2, C=1, Be=10, P=10 → total_sku=8; pct=25.0 > 20
    over = _job(
        status="completed",
        units=(
            _unit(
                sku_stats=SkuStats(
                    applied=5,
                    kept_previous=2,
                    skipped_no_baseline=1,
                    blocked_empty=10,
                    product_swap_blocked=10,
                ),
            ),
        ),
    )
    assert kept_alert_text(over, Decimal("20")) == (
        "⚠️ Matrix deploy: high kept_previous (Bk/total_sku = 25.0%)\n"
        "Threshold: 20%\n"
        "SKU kept_previous: 2 / total_sku: 8"
    )

    # exactly at threshold → no alert
    equal = _job(
        status="completed",
        units=(_unit(sku_stats=SkuStats(applied=8, kept_previous=2)),),
    )
    assert kept_alert_text(equal, Decimal("20")) is None

    # Be/P only → total_sku=0 → no alert
    only_be_p = _job(
        status="completed",
        units=(_unit(sku_stats=SkuStats(blocked_empty=5, product_swap_blocked=5)),),
    )
    assert kept_alert_text(only_be_p, Decimal("20")) is None


def test_swap_blocked_line_renders_empty_desired_product_marker() -> None:
    job = _job(
        status="completed",
        units=(
            _unit(
                sku_stats=SkuStats(applied=1, product_swap_blocked=1),
                swap_lines=(
                    ProductSwapBlockedLine(
                        machine_code="512",
                        line_number=3,
                        current_product="ABC",
                        desired_product=None,
                        reason="stock_positive",
                    ),
                ),
            ),
        ),
    )
    text = format_main_summary(job, global_abort_reason=None, max_price_delta_pct=_DELTA)
    assert "512 L3 ABC → (empty) (stock_positive)" in text
