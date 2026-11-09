from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.build_deploy_payloads import BuildMatrixDeployPayloads
from src.application.matrix_automation.models import PurchaseAttributesFetchResult
from src.application.matrix_automation.ports import RunMatrixDeployBuildPort

from .fakes import _CountingPurchaseReader, _runner, _SnapshotStore


def test_run_matrix_deploy_build_satisfies_port() -> None:
    reader = _CountingPurchaseReader(prices={})
    runner = _runner(reader=reader)
    assert isinstance(runner, RunMatrixDeployBuildPort)


def test_build_payloads_without_purchase_attributes_raises_without_per_cell_fetch() -> None:
    class _ForbiddenReader:
        fetch_count = 0

        def fetch_attributes(
            self,
            product_codes: frozenset[str],
        ) -> PurchaseAttributesFetchResult:
            self.fetch_count += 1
            raise AssertionError("per-cell fetch must not be called")

    reader = _ForbiddenReader()
    with pytest.raises(TypeError, match="purchase_attributes"):
        BuildMatrixDeployPayloads(
            snapshot_store=_SnapshotStore(),
            purchase_reader=reader,  # type: ignore[arg-type]
            blocking_cell_price=Decimal("999"),
            max_price_delta_pct=Decimal("30"),
            base_margin=curved_margin_params(),
            product_multipliers={"MS-1": Decimal("1")},
        )
    assert reader.fetch_count == 0
