from __future__ import annotations

from beartype import beartype

from src.application.snack_loading.issue_inventory_link import (
    IssuedSnackInventoryLink,
    IssueSnackInventoryLink,
)
from src.application.snack_loading.ports import (
    SnackInventoryCellsSource,
    SnackInventoryFormMode,
)
from src.domain.ids import TechnicianId

NO_SNACK_MATRIX_MESSAGE = "Нет матрицы для инвентаризации снека."


@beartype
def snack_inventory_workspace_flags(
    *,
    machine_code: str,
    cells_source: SnackInventoryCellsSource | None,
    issuer: IssueSnackInventoryLink | None,
) -> dict[str, bool]:
    if issuer is None or cells_source is None:
        return {
            "snack_inventory_available": False,
            "snack_inventory_show_stub": False,
        }
    has_cells = bool(cells_source.list_cells(machine_code))
    return {
        "snack_inventory_available": has_cells,
        "snack_inventory_show_stub": not has_cells,
    }


@beartype
def issue_snack_inventory_link_for_mode(
    *,
    machine_code: str,
    mode: SnackInventoryFormMode,
    technician_id: TechnicianId,
    cells_source: SnackInventoryCellsSource,
    issuer: IssueSnackInventoryLink,
) -> IssuedSnackInventoryLink | str:
    cells = tuple(cells_source.list_cells(machine_code))
    if not cells:
        return NO_SNACK_MATRIX_MESSAGE
    return issuer.execute(
        machine_code=machine_code,
        mode=mode,
        cells=cells,
        technician_id=technician_id,
    )
