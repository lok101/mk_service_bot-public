from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from beartype import beartype

from src.application.matrix_automation.ports import MatrixPriceSnapshotStore
from src.application.snack_loading.ports import InventoryFormCell, SnackInventoryCellsSource


@beartype
@dataclass(frozen=True, slots=True)
class SnapshotSnackInventoryCellsSource(SnackInventoryCellsSource):
    snapshot_store: MatrixPriceSnapshotStore

    @beartype
    def list_cells(self, machine_code: str) -> Sequence[InventoryFormCell]:
        documents = self.snapshot_store.list_latest_for_machine(machine_code=machine_code)
        cells: list[InventoryFormCell] = []
        for document in documents:
            for line in document.lines:
                if line.outcome == "blocked_empty":
                    continue
                if not line.product_code:
                    continue
                cells.append(
                    InventoryFormCell(
                        matrix_name=document.logical_matrix_name,
                        line_number=line.line_number,
                        product_code=line.product_code,
                        product_name=line.product_name or "",
                    ),
                )
        cells.sort(key=lambda item: (item.matrix_name, item.line_number, item.product_code))
        return tuple(cells)
