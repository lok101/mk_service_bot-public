from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.models import (
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixParseState,
)

from .fakes import _builder


def test_build_payload_for_enabled_matrix_unit() -> None:
    state = MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1.0"),
                cells=(
                    MatrixCatalogCell(1, "Кола 0.5", "MS-1"),
                    MatrixCatalogCell(2, "", None),
                ),
            ),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = _builder()(
        state,
    )
    assert len(result.payloads) == 1
    assert result.payloads[0].machine_code == "512"
    assert len(result.payloads[0].lines) == 2
    assert result.payloads[0].lines[1].outcome == "blocked_empty"


def test_two_machines_produce_two_payloads() -> None:
    state = MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512", "513"),
                matrix_multiplier=Decimal("1.0"),
                cells=(MatrixCatalogCell(1, "Кола 0.5", "MS-1"),),
            ),
        ),
        blocked_matrices=(),
        product_block_map={},
        auto_sync_disabled_matrices=0,
    )
    result = _builder()(state)
    assert len(result.payloads) == 2
    assert {payload.machine_code for payload in result.payloads} == {"512", "513"}
