from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.errors import PurchasePricesBatchError
from src.application.matrix_automation.models import (
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    PurchaseAttributesFetchResult,
)
from src.application.matrix_automation.run_matrix_deploy_build import (
    PurchaseFetchGlobalAbort,
)

from .fakes import _CountingPurchaseReader, _runner, _state


def test_cards_found_zero_returns_global_abort() -> None:
    reader = _CountingPurchaseReader(prices={}, cards_found=0)
    state = _state(
        matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1"),
                cells=(MatrixCatalogCell(1, "Кола 0.5", "MS-1"),),
            ),
        ),
    )
    result = _runner(reader=reader)(state)
    assert isinstance(result, PurchaseFetchGlobalAbort)
    assert result.reason == "moysklad_batch_empty_response"
    assert reader.fetch_count == 1


def test_cards_found_positive_empty_attributes_product_blocks_not_abort() -> None:
    reader = _CountingPurchaseReader(prices={}, cards_found=1)
    state = _state(
        matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1"),
                cells=(MatrixCatalogCell(1, "Кола 0.5", "MS-1"),),
            ),
        ),
    )
    result = _runner(reader=reader)(state)
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert result.payloads == ()
    assert len(result.skipped_units) == 1
    assert result.skipped_units[0].deploy_reason == "product_reference_invalid"


def test_partial_ms_missing_code_blocks_only_affected_matrix() -> None:
    reader = _CountingPurchaseReader(prices={"MS-1": ("10.00", 12)})
    state = _state(
        matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1"),
                cells=(
                    MatrixCatalogCell(1, "Кола 0.5", "MS-1"),
                    MatrixCatalogCell(2, "Water", "MS-2"),
                ),
            ),
            EnabledLogicalMatrix(
                logical_matrix_name="Drinks",
                machine_codes=("777",),
                matrix_multiplier=Decimal("1"),
                cells=(MatrixCatalogCell(1, "Juice", "MS-1"),),
            ),
        ),
    )
    result = _runner(reader=reader)(state)
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert len(result.payloads) == 1
    assert result.payloads[0].logical_matrix_name == "Drinks"
    assert len(result.skipped_units) == 1
    assert result.skipped_units[0].logical_matrix_name == "Snacks"
    assert result.skipped_units[0].deploy_reason == "product_reference_invalid"


def test_union_empty_skips_fetch() -> None:
    reader = _CountingPurchaseReader(prices={})
    state = _state(matrices=())
    result = _runner(reader=reader)(state)
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert reader.fetch_count == 0


def test_union_non_empty_total_fail_returns_global_abort() -> None:
    class _FailingReader:
        fetch_count = 0

        def fetch_attributes(
            self,
            product_codes: frozenset[str],
        ) -> PurchaseAttributesFetchResult:
            self.fetch_count += 1
            raise PurchasePricesBatchError("ms down")

    reader = _FailingReader()
    state = _state(
        matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1"),
                cells=(MatrixCatalogCell(1, "Кола 0.5", "MS-1"),),
            ),
        ),
    )
    result = _runner(reader=reader)(state)  # type: ignore[arg-type]
    assert isinstance(result, PurchaseFetchGlobalAbort)
    assert result.reason == "ms down"
    assert reader.fetch_count == 1


def test_single_batch_fetch_per_job() -> None:
    reader = _CountingPurchaseReader(
        prices={
            "MS-1": ("10.00", 12),
            "MS-2": ("10.00", 12),
        },
    )
    state = _state(
        matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1"),
                cells=(
                    MatrixCatalogCell(1, "Кола 0.5", "MS-1"),
                    MatrixCatalogCell(2, "Water", "MS-2"),
                ),
            ),
            EnabledLogicalMatrix(
                logical_matrix_name="Drinks",
                machine_codes=("777",),
                matrix_multiplier=Decimal("1"),
                cells=(MatrixCatalogCell(1, "Juice", "MS-2"),),
            ),
        ),
    )
    result = _runner(reader=reader)(state)
    assert not isinstance(result, PurchaseFetchGlobalAbort)
    assert reader.fetch_count == 1
    assert len(result.payloads) == 2
