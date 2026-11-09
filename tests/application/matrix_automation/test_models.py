from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from src.application.matrix_automation import (
    BlockedMatrixEntry,
    BuildMatrixDeployResult,
    EnabledLogicalMatrix,
    MatrixDeployPayload,
    MatrixDeployPayloadLine,
    MatrixDeployResult,
    MatrixDeploySkippedUnit,
    MatrixParseState,
)
from src.application.matrix_automation.deploy_reasons import UNKNOWN_PRODUCT_NAME


def test_matrix_parse_state_is_frozen() -> None:
    state = MatrixParseState(
        enabled_matrices=(),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    with pytest.raises(FrozenInstanceError):
        state.auto_sync_disabled_matrices = 1  # type: ignore[misc]


def test_blocked_matrix_entry_carries_machine_codes() -> None:
    entry = BlockedMatrixEntry(
        logical_matrix_name="Snacks",
        deploy_reason=UNKNOWN_PRODUCT_NAME,
        detail="unknown_product_name: X",
        products=(),
        machine_codes=("512",),
    )
    assert entry.machine_codes == ("512",)


def test_build_result_groups_payloads_and_skipped_units() -> None:
    result = BuildMatrixDeployResult(payloads=(), skipped_units=())
    assert result.payloads == ()
    assert result.skipped_units == ()


def test_deploy_payload_line_supports_blocked_empty_outcome() -> None:
    from decimal import Decimal

    line = MatrixDeployPayloadLine(
        line_number=2,
        product_code=None,
        product_name="",
        deploy_price=Decimal("999"),
        capacity=0,
        outcome="blocked_empty",
        reason=None,
        strong_price_increase=False,
    )
    assert line.outcome == "blocked_empty"


def test_enabled_logical_matrix_is_frozen() -> None:
    from decimal import Decimal

    from src.application.matrix_automation.models import MatrixCatalogCell

    matrix = EnabledLogicalMatrix(
        logical_matrix_name="Snacks",
        machine_codes=("512",),
        matrix_multiplier=Decimal("1"),
        cells=(MatrixCatalogCell(1, "Cola", "A"),),
    )
    with pytest.raises(FrozenInstanceError):
        matrix.logical_matrix_name = "Other"  # type: ignore[misc]


def test_skipped_unit_allows_none_sku_stats() -> None:
    unit = MatrixDeploySkippedUnit(
        logical_matrix_name="Snacks",
        machine_code="512",
        deploy_status="skipped",
        deploy_reason=UNKNOWN_PRODUCT_NAME,
        sku_stats=None,
    )
    assert unit.sku_stats is None


def test_deploy_payload_carries_machine_code() -> None:
    payload = MatrixDeployPayload(
        logical_matrix_name="Snacks",
        machine_code="512",
        matrix_multiplier="1.0",
        lines=(),
    )
    assert payload.machine_code == "512"


def test_deploy_result_carries_unit_key_and_reason_contract() -> None:
    result = MatrixDeployResult(
        logical_matrix_name="Snacks",
        machine_code="512",
        status="failed",
        reason="load_timeout",
    )
    assert result.logical_matrix_name == "Snacks"
    assert result.machine_code == "512"
    assert result.status == "failed"
    assert result.reason == "load_timeout"


def test_applied_result_has_no_reason() -> None:
    result = MatrixDeployResult(
        logical_matrix_name="Snacks",
        machine_code="512",
        status="applied",
        reason=None,
    )
    assert result.reason is None


def test_deploy_result_is_frozen() -> None:
    result = MatrixDeployResult("Snacks", "512", "applied", None)
    with pytest.raises(FrozenInstanceError):
        result.status = "failed"  # type: ignore[misc]


def test_failure_reason_includes_kit_machine_lookup_failed() -> None:
    from typing import get_args

    from src.application.matrix_automation.models import MatrixDeployFailureReason

    assert "kit_machine_lookup_failed" in get_args(MatrixDeployFailureReason)


def test_deploy_result_accepts_kit_machine_lookup_failed_reason() -> None:
    result = MatrixDeployResult(
        logical_matrix_name="Snacks",
        machine_code="512",
        status="failed",
        reason="kit_machine_lookup_failed",
    )
    assert result.reason == "kit_machine_lookup_failed"
