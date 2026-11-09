from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation import MatrixParseState
from src.application.matrix_automation.ports import MatrixPriceSnapshotStore
from src.application.snack_loading.loading_plan import SnackLoadingCellInput
from src.application.snack_loading.ports import SnackMachineStockStore


@beartype
@dataclass(slots=True)
class DesiredCatalogIndex:
    """Desired product by (logical_matrix_name, line_number) for a machine."""

    _by_machine: dict[str, dict[tuple[str, int], str | None]] = field(default_factory=dict)

    @beartype
    def replace_from_parse_state(self, state: MatrixParseState) -> None:
        by_machine: dict[str, dict[tuple[str, int], str | None]] = {}
        for matrix in state.enabled_matrices:
            for machine_code in matrix.machine_codes:
                bucket = by_machine.setdefault(machine_code, {})
                for cell in matrix.cells:
                    bucket[(matrix.logical_matrix_name, cell.line_number)] = cell.product_code
        self._by_machine = by_machine

    @beartype
    def desired(
        self,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> str | None:
        return self._by_machine.get(machine_code, {}).get((logical_matrix_name, line_number))


@beartype
@dataclass(frozen=True, slots=True)
class SnapshotSnackLoadingCellSource:
    snapshot_store: MatrixPriceSnapshotStore
    stock_store: SnackMachineStockStore
    desired_index: DesiredCatalogIndex
    food_product_codes: frozenset[str] = frozenset()

    @beartype
    def list_plan_cells(self, machine_code: str) -> Sequence[SnackLoadingCellInput]:
        stock = self.stock_store.load(machine_code)
        documents = self.snapshot_store.list_latest_for_machine(machine_code=machine_code)
        cells: list[SnackLoadingCellInput] = []
        for document in documents:
            for line in document.lines:
                if line.outcome == "blocked_empty":
                    continue
                if not line.product_code:
                    continue
                current = Decimal("0")
                if stock is not None:
                    current = stock.qty(
                        machine_code,
                        document.logical_matrix_name,
                        line.line_number,
                    )
                desired = self.desired_index.desired(
                    machine_code,
                    document.logical_matrix_name,
                    line.line_number,
                )
                if desired is None:
                    desired = line.product_code
                cells.append(
                    SnackLoadingCellInput(
                        machine_code=machine_code,
                        logical_matrix_name=document.logical_matrix_name,
                        line_number=line.line_number,
                        product_code=line.product_code,
                        capacity=line.capacity,
                        current_qty=current,
                        desired_product=desired,
                        snapshot_product=line.product_code,
                        is_food=line.product_code in self.food_product_codes,
                    )
                )
        cells.sort(key=lambda c: (c.logical_matrix_name, c.line_number, c.product_code))
        return tuple(cells)
