from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from src.application.matrix_automation.deploy_reasons import PRODUCT_REFERENCE_INVALID
from src.application.matrix_automation.errors import PurchasePricesBatchError
from src.application.matrix_automation.models import (
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    PriceSnapshotDocument,
    SnapshotLineRecord,
)
from src.application.matrix_automation.ms_union import (
    collect_catalog_product_codes,
    collect_guard_current_product_codes,
    product_level_blocks_from_missing_skus,
    purchase_fetch_global_abort_reason,
    should_fetch_purchase_attributes,
)


def _matrix(
    *,
    name: str = "Snacks",
    machine_codes: tuple[str, ...] = ("512",),
    codes: tuple[str, ...] | None = None,
    cells: tuple[MatrixCatalogCell, ...] | None = None,
) -> EnabledLogicalMatrix:
    if cells is None:
        assert codes is not None
        cells = tuple(
            MatrixCatalogCell(line_number=index + 1, product_name=f"P{index}", product_code=code)
            for index, code in enumerate(codes)
        )
    return EnabledLogicalMatrix(
        logical_matrix_name=name,
        machine_codes=machine_codes,
        matrix_multiplier=Decimal("1"),
        cells=cells,
    )


def _snapshot_line(product_code: str | None) -> PriceSnapshotDocument:
    return PriceSnapshotDocument(
        job_id="job-1",
        machine_code="512",
        logical_matrix_name="Snacks",
        recorded_at="2026-07-08T10:00:00Z",
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code=product_code,
                product_name="" if product_code is None else "Prev",
                capacity=12,
                purchase_price="10.00",
                calculated_price="50.00",
                deploy_price="50.00",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )


class _SnapshotStore:
    def __init__(
        self,
        mapping: Mapping[tuple[str, str, int], PriceSnapshotDocument],
    ) -> None:
        self._mapping = {
            key: PriceSnapshotDocument(
                job_id=doc.job_id,
                machine_code=key[0],
                logical_matrix_name=key[1],
                recorded_at=doc.recorded_at,
                lines=(
                    SnapshotLineRecord(
                        line_number=key[2],
                        product_code=doc.lines[0].product_code,
                        product_name=doc.lines[0].product_name,
                        capacity=doc.lines[0].capacity,
                        purchase_price=doc.lines[0].purchase_price,
                        calculated_price=doc.lines[0].calculated_price,
                        deploy_price=doc.lines[0].deploy_price,
                        outcome=doc.lines[0].outcome,
                        reason=doc.lines[0].reason,
                        strong_price_increase=doc.lines[0].strong_price_increase,
                    ),
                ),
            )
            for key, doc in mapping.items()
        }

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> PriceSnapshotDocument | None:
        return self._mapping.get((machine_code, logical_matrix_name, line_number))

    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        return any(
            key[0] == machine_code and key[1] == logical_matrix_name for key in self._mapping
        )

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: PriceSnapshotDocument) -> None:
        return None


def test_union_empty_skips_fetch() -> None:
    codes = collect_catalog_product_codes((), product_block_map={})
    assert codes == frozenset()
    assert should_fetch_purchase_attributes(codes) is False


def test_union_non_empty_total_fail_global_abort_reason() -> None:
    error = PurchasePricesBatchError("ms down")
    assert purchase_fetch_global_abort_reason(error) == "ms down"


def test_missing_catalog_sku_adds_product_level_blocks() -> None:
    matrices = (_matrix(name="Snacks", codes=("A", "B")), _matrix(name="Drinks", codes=("C",)))
    requested = frozenset({"A", "B", "C"})
    returned = frozenset({"A", "C"})
    blocked = product_level_blocks_from_missing_skus(
        enabled_matrices=matrices,
        requested_codes=requested,
        returned_codes=returned,
    )
    assert len(blocked) == 1
    assert blocked[0].logical_matrix_name == "Snacks"
    assert blocked[0].deploy_reason == PRODUCT_REFERENCE_INVALID
    assert blocked[0].detail == "moysklad_fetch_failed: B"


def test_blocked_product_code_excluded_from_union() -> None:
    matrices = (_matrix(name="Snacks", codes=("MS-1",)),)
    codes = collect_catalog_product_codes(
        matrices,
        product_block_map={"MS-1": object()},
    )
    assert codes == frozenset()


def test_multiple_missing_skus_use_sorted_first_code_in_detail() -> None:
    matrices = (_matrix(name="Snacks", codes=("B", "A")),)
    blocked = product_level_blocks_from_missing_skus(
        enabled_matrices=matrices,
        requested_codes=frozenset({"B", "A"}),
        returned_codes=frozenset(),
    )
    assert blocked[0].detail == "moysklad_fetch_failed: A"


def test_missing_catalog_sku_block_fills_products() -> None:
    matrices = (_matrix(name="Snacks", codes=("A", "B")),)
    blocked = product_level_blocks_from_missing_skus(
        enabled_matrices=matrices,
        requested_codes=frozenset({"A", "B"}),
        returned_codes=frozenset({"A"}),
    )
    assert len(blocked) == 1
    assert blocked[0].detail == "moysklad_fetch_failed: B"
    assert len(blocked[0].products) >= 1
    assert any(ref.product_code == "B" for ref in blocked[0].products)


def test_guard_current_codes_include_only_non_null_changed_snapshot_sku() -> None:
    store = _SnapshotStore(
        {
            ("512", "Snacks", 1): _snapshot_line("OLD"),
            ("512", "Snacks", 2): _snapshot_line("SAME"),
            ("512", "Snacks", 3): _snapshot_line(None),
        }
    )
    matrix = _matrix(
        machine_codes=("512",),
        cells=(
            MatrixCatalogCell(1, "New", "NEW"),
            MatrixCatalogCell(2, "Same", "SAME"),
            MatrixCatalogCell(3, "First", "FIRST"),
        ),
    )
    assert collect_guard_current_product_codes((matrix,), snapshot_store=store) == {"OLD"}


def test_guard_current_codes_include_product_to_empty_transition() -> None:
    store = _SnapshotStore({("512", "Snacks", 1): _snapshot_line("OLD")})
    matrix = _matrix(cells=(MatrixCatalogCell(1, "", None),))
    assert collect_guard_current_product_codes((matrix,), snapshot_store=store) == {"OLD"}


def test_missing_guard_current_sku_is_not_product_level_block() -> None:
    blocked = product_level_blocks_from_missing_skus(
        enabled_matrices=(_matrix(cells=(MatrixCatalogCell(1, "New", "NEW"),)),),
        requested_codes=frozenset({"NEW", "OLD"}),
        returned_codes=frozenset({"NEW"}),
    )
    assert blocked == ()


def test_missing_catalog_desired_sku_still_blocks_affected_matrix() -> None:
    blocked = product_level_blocks_from_missing_skus(
        enabled_matrices=(_matrix(cells=(MatrixCatalogCell(1, "New", "NEW"),)),),
        requested_codes=frozenset({"NEW", "OLD"}),
        returned_codes=frozenset({"OLD"}),
    )
    assert len(blocked) == 1
    assert blocked[0].deploy_reason == "product_reference_invalid"
