from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.application.matrix_automation.models import PriceSnapshotDocument, SnapshotLineRecord
from src.infrastructure.snack_loading.food_product_codes import (
    food_product_codes_for_cli,
    product_codes_under_path_name,
)
from src.infrastructure.snack_loading.plan_cells import (
    DesiredCatalogIndex,
    SnapshotSnackLoadingCellSource,
)
from src.infrastructure.testing.snack_loading_fakes import InMemorySnackMachineStockStore

_FOOD_PATH = "Основной склад/СНЕК/Еда"
_MACHINE = "M1"


def test_food_product_codes_from_path_name_prefix() -> None:
    rows = [
        {"code": "FOOD1", "pathName": f"{_FOOD_PATH}/Сэндвичи"},
        {"code": "FOOD2", "pathName": _FOOD_PATH},
        {"code": "SNACK1", "pathName": "Основной склад/СНЕК/Батончики"},
        {"code": "  ", "pathName": f"{_FOOD_PATH}/Bad"},
        {"code": "NO_PATH", "name": "x"},
    ]

    codes = product_codes_under_path_name(rows, path_prefix=_FOOD_PATH)

    assert codes == frozenset({"FOOD1", "FOOD2"})


@dataclass(slots=True)
class _FakeSnapshotStore:
    documents: tuple[PriceSnapshotDocument, ...]

    def list_latest_for_machine(self, *, machine_code: str) -> Sequence[PriceSnapshotDocument]:
        del machine_code
        return self.documents

    def has_unit_snapshot(self, *, machine_code: str, logical_matrix_name: str) -> bool:
        del machine_code, logical_matrix_name
        return True

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> PriceSnapshotDocument | None:
        del machine_code, logical_matrix_name, line_number
        return None

    def save(self, document: PriceSnapshotDocument) -> None:
        del document


def test_cell_source_marks_is_food_from_codes() -> None:
    document = PriceSnapshotDocument(
        job_id="job-1",
        machine_code=_MACHINE,
        logical_matrix_name="matrix-a",
        recorded_at="2026-07-30T00:00:00+00:00",
        lines=(
            SnapshotLineRecord(
                line_number=1,
                product_code="F",
                product_name="Food",
                capacity=5,
                purchase_price=None,
                calculated_price=None,
                deploy_price="10",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
            SnapshotLineRecord(
                line_number=2,
                product_code="S",
                product_name="Snack",
                capacity=10,
                purchase_price=None,
                calculated_price=None,
                deploy_price="20",
                outcome="applied",
                reason=None,
                strong_price_increase=False,
            ),
        ),
    )
    source = SnapshotSnackLoadingCellSource(
        snapshot_store=_FakeSnapshotStore(documents=(document,)),
        stock_store=InMemorySnackMachineStockStore(),
        desired_index=DesiredCatalogIndex(),
        food_product_codes=frozenset({"F"}),
    )

    cells = source.list_plan_cells(_MACHINE)

    by_code = {cell.product_code: cell.is_food for cell in cells}
    assert by_code == {"F": True, "S": False}


def test_food_codes_not_loaded_when_handle_food_products_false() -> None:
    calls: list[int] = []

    def _load() -> frozenset[str]:
        calls.append(1)
        return frozenset({"F"})

    codes = food_product_codes_for_cli(
        handle_food_products=False,
        ms_configured=True,
        load_codes=_load,
    )

    assert codes == frozenset()
    assert calls == []
