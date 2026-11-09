from __future__ import annotations

import pytest

from src.application.matrix_automation.loading_policy import DefaultMatrixCellLoadingPolicy
from src.application.matrix_automation.ports import (
    MatrixCellLoadingPolicy,
    MatrixStockProvider,
)


class _StockProvider:
    def current_stock(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        product_code: str,
    ) -> int | None:
        return 0


def test_stock_provider_satisfies_runtime_protocol() -> None:
    assert isinstance(_StockProvider(), MatrixStockProvider)


def test_default_loading_policy_satisfies_runtime_protocol() -> None:
    assert isinstance(DefaultMatrixCellLoadingPolicy(), MatrixCellLoadingPolicy)


@pytest.mark.parametrize(
    ("desired", "snapshot", "blocked"),
    [
        ("NEW", None, False),
        (None, None, False),
        ("SAME", "SAME", False),
        ("NEW", "OLD", True),
        (None, "OLD", True),
    ],
)
def test_default_loading_policy_delegates_pending_swap_rule(
    desired: str | None,
    snapshot: str | None,
    blocked: bool,
) -> None:
    policy = DefaultMatrixCellLoadingPolicy()
    assert (
        policy.is_loading_blocked(
            desired_product=desired,
            snapshot_product=snapshot,
        )
        is blocked
    )
