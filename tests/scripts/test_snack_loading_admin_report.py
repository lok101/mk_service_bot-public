from __future__ import annotations

import json
from decimal import Decimal

from scripts.snack_loading_admin import format_plan_only_report

from src.application.snack_loading.loading_plan import (
    BlockedByLoadingPolicyCell,
    ShortageReport,
    SkippedSmallMoveReport,
    SnackLoadingPlan,
)
from src.application.snack_loading.run_loading import (
    ApparatusRunResult,
    SnackLoadingRunResult,
)


def test_format_plan_only_report_includes_shortages_and_blocked() -> None:
    plan = SnackLoadingPlan(
        lines=(),
        positions=(),
        shortages=(
            ShortageReport(
                machine_code="M1",
                product_code="SKU1",
                needed_qty=Decimal("5"),
                available_on_main_qty=Decimal("1"),
                shortage_qty=Decimal("4"),
            ),
        ),
        skipped_small_moves=(
            SkippedSmallMoveReport(
                machine_code="M1",
                product_code="SKU2",
                total_capacity=100,
                min_move_fraction=0.15,
                threshold_qty=Decimal("15"),
                shipped_before_threshold=Decimal("2"),
            ),
        ),
        anomalies=(),
        blocked_by_loading_policy=(
            BlockedByLoadingPolicyCell(
                machine_code="M1",
                logical_matrix_name="mx",
                line_number=3,
                desired_product="A",
                snapshot_product="B",
            ),
        ),
    )
    result = SnackLoadingRunResult(
        run_id="run-plan",
        apparatus_results=(ApparatusRunResult(machine_code="M1", status="ok", plan=plan),),
        exit_code=0,
    )

    payload = json.loads(format_plan_only_report(result))

    assert "shortages" in payload
    assert "skipped_small_moves" in payload
    assert "anomalies" in payload
    assert "blocked_by_loading_policy" in payload
    assert "apparatus_results" in payload
    assert payload["shortages"][0]["product_code"] == "SKU1"
    assert payload["blocked_by_loading_policy"][0]["line_number"] == 3
    assert payload["apparatus_results"][0]["machine_code"] == "M1"
