from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.models import (
    MatrixDeployPayload,
    MatrixDeployPayloadLine,
    MatrixDeployResult,
)
from src.application.snack_loading import record_kit_matrix_deploy
from src.infrastructure.composition.wiring.wire_matrix_worker import wrap_deployer_with_deploy_map
from src.infrastructure.testing.snack_loading_fakes import InMemoryKitMatrixDeployMapStore


def test_record_kit_matrix_deploy_from_applied_result() -> None:
    store = InMemoryKitMatrixDeployMapStore()
    result = MatrixDeployResult(
        logical_matrix_name="SnackA",
        machine_code="514",
        status="applied",
        reason=None,
        kit_matrix_id=42,
    )
    record_kit_matrix_deploy(
        store,
        result=result,
        vending_machine_id=7,
        kit_matrix_name="SnackA_514_2026-07-27",
    )
    assert store.get(42) is not None


def test_record_skips_failed_without_id() -> None:
    store = InMemoryKitMatrixDeployMapStore()
    result = MatrixDeployResult(
        logical_matrix_name="SnackA",
        machine_code="514",
        status="failed",
        reason="upload_failed",
        kit_matrix_id=None,
    )
    record_kit_matrix_deploy(store, result=result, vending_machine_id=None, kit_matrix_name=None)
    assert store.get(1) is None  # nothing upserted


class _FakeAppliedDeployer:
    def deploy(self, payloads: list[MatrixDeployPayload]) -> list[MatrixDeployResult]:
        return [
            MatrixDeployResult(
                logical_matrix_name=payload.logical_matrix_name,
                machine_code=payload.machine_code,
                status="applied",
                reason=None,
                kit_matrix_id=42,
                vending_machine_id=7,
                kit_matrix_name="SnackA_514_2026-07-27",
            )
            for payload in payloads
        ]


def test_recording_deployer_upserts_map_on_applied() -> None:
    store = InMemoryKitMatrixDeployMapStore()
    deployer = wrap_deployer_with_deploy_map(_FakeAppliedDeployer(), store)
    payload = MatrixDeployPayload(
        logical_matrix_name="SnackA",
        machine_code="514",
        matrix_multiplier="1.0",
        lines=(
            MatrixDeployPayloadLine(
                line_number=1,
                product_code="SKU1",
                product_name="Snack",
                deploy_price=Decimal("10"),
                capacity=5,
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )
    results = deployer.deploy([payload])
    assert results[0].status == "applied"
    row = store.get(42)
    assert row is not None
    assert row.machine_code == "514"
    assert row.vending_machine_id == 7
