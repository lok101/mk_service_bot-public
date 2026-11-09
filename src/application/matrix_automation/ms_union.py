from __future__ import annotations

from collections.abc import Mapping

from beartype import beartype

from src.application.matrix_automation.deploy_reasons import PRODUCT_REFERENCE_INVALID
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    BlockedProductRef,
    EnabledLogicalMatrix,
    MatrixParseState,
    PriceSnapshotDocument,
)
from src.application.matrix_automation.ports import MatrixPriceSnapshotStore
from src.domain.matrix_pricing import detect_pending_product_swap


@beartype
def should_fetch_purchase_attributes(codes: frozenset[str]) -> bool:
    return bool(codes)


@beartype
def purchase_fetch_global_abort_reason(exc: BaseException) -> str:
    return str(exc)


@beartype
def collect_catalog_product_codes(
    enabled_matrices: tuple[EnabledLogicalMatrix, ...],
    *,
    product_block_map: Mapping[str, object],
) -> frozenset[str]:
    codes: set[str] = set()
    for matrix in enabled_matrices:
        for cell in matrix.cells:
            if cell.product_code is None:
                continue
            if cell.product_code in product_block_map:
                continue
            if cell.product_name in product_block_map:
                continue
            codes.add(cell.product_code)
    return frozenset(codes)


@beartype
def enabled_matrices_with_seed_candidates(
    state: MatrixParseState,
    *,
    snapshot_store: MatrixPriceSnapshotStore,
) -> tuple[EnabledLogicalMatrix, ...]:
    blocked_names = {entry.logical_matrix_name for entry in state.blocked_matrices}
    selected: list[EnabledLogicalMatrix] = []
    for matrix in state.enabled_matrices:
        if matrix.logical_matrix_name in blocked_names:
            continue
        for machine_code in matrix.machine_codes:
            if not snapshot_store.has_unit_snapshot(
                machine_code=machine_code,
                logical_matrix_name=matrix.logical_matrix_name,
            ):
                selected.append(matrix)
                break
    return tuple(selected)


@beartype
def _product_code_for_line(
    document: PriceSnapshotDocument | None,
    line_number: int,
) -> str | None:
    if document is None:
        return None
    for line in document.lines:
        if line.line_number == line_number:
            return line.product_code
    return None


@beartype
def collect_guard_current_product_codes(
    enabled_matrices: tuple[EnabledLogicalMatrix, ...],
    *,
    snapshot_store: MatrixPriceSnapshotStore,
) -> frozenset[str]:
    codes: set[str] = set()
    for matrix in enabled_matrices:
        for machine_code in matrix.machine_codes:
            for cell in matrix.cells:
                document = snapshot_store.get_latest_line(
                    machine_code=machine_code,
                    logical_matrix_name=matrix.logical_matrix_name,
                    line_number=cell.line_number,
                )
                current = _product_code_for_line(document, cell.line_number)
                if detect_pending_product_swap(
                    desired_product=cell.product_code,
                    snapshot_product=current,
                ):
                    assert current is not None
                    codes.add(current)
    return frozenset(codes)


@beartype
def product_level_blocks_from_missing_skus(
    *,
    enabled_matrices: tuple[EnabledLogicalMatrix, ...],
    requested_codes: frozenset[str],
    returned_codes: frozenset[str],
) -> tuple[BlockedMatrixEntry, ...]:
    missing = requested_codes - returned_codes
    if not missing:
        return ()
    blocked: list[BlockedMatrixEntry] = []
    for matrix in enabled_matrices:
        matrix_missing_products: list[BlockedProductRef] = []
        for cell in matrix.cells:
            if cell.product_code is None or cell.product_code not in missing:
                continue
            product_name = cell.product_name or "(unknown)"
            matrix_missing_products.append(
                BlockedProductRef(
                    product_name=product_name,
                    product_code=cell.product_code,
                ),
            )
        if not matrix_missing_products:
            continue
        blocked.append(
            BlockedMatrixEntry(
                logical_matrix_name=matrix.logical_matrix_name,
                deploy_reason=PRODUCT_REFERENCE_INVALID,
                detail=f"moysklad_fetch_failed: {sorted(missing)[0]}",
                products=tuple(matrix_missing_products),
                machine_codes=matrix.machine_codes,
            ),
        )
    return tuple(blocked)
