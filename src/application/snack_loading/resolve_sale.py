from __future__ import annotations

from typing import Literal

from beartype import beartype

from src.domain.machine_sales import SaleKind
from src.domain.snack_loading.events import CellKey

SnackSaleResolveStatus = Literal[
    "resolved",
    "unresolved_matrix",
    "unresolved_machine",
    "unresolved_line",
    "product_mismatch",
    "skipped_non_snack",
]

DeployMapRow = tuple[str, str]


@beartype
def resolve_snack_sale(
    *,
    sale_kind: SaleKind,
    kit_matrix_id: int | None,
    machine_code: str,
    kit_line_number: int | None,
    product_code: str,
    deploy_map_row: DeployMapRow | None,
    snapshot_product: str | None,
) -> tuple[SnackSaleResolveStatus, CellKey | None]:
    if sale_kind != "snack":
        return "skipped_non_snack", None

    if kit_matrix_id is None or deploy_map_row is None:
        return "unresolved_matrix", None

    logical_matrix_name, mapped_machine_code = deploy_map_row
    if machine_code != mapped_machine_code:
        return "unresolved_machine", None

    if kit_line_number is None or kit_line_number < 1:
        return "unresolved_line", None

    if snapshot_product != product_code:
        return "product_mismatch", None

    return "resolved", (machine_code, logical_matrix_name, kit_line_number)
