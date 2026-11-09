from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)


def _layout(
    code: str,
    name: str,
    *,
    cells: tuple[SnackMachineLayoutCell, ...] = (),
) -> SnackMachineLayout:
    return SnackMachineLayout(
        machine_code=code,
        logical_matrix_name=name,
        matrix_multiplier=Decimal("1.0"),
        auto_sync_enabled=True,
        cells=cells,
    )


def test_layout_store_upsert_by_machine_code() -> None:
    store = InMemorySnackMachineLayoutStore()
    store.upsert(_layout("514", "TwinA"))
    store.upsert(
        _layout(
            "514",
            "TwinA",
            cells=(SnackMachineLayoutCell(line_number=1, product_code="P1"),),
        )
    )
    got = store.get("514")
    assert got is not None
    assert got.cells[0].product_code == "P1"
    assert store.count() == 1


def test_layout_store_allows_duplicate_logical_matrix_name() -> None:
    store = InMemorySnackMachineLayoutStore()
    store.upsert(_layout("514", "SameTab"))
    store.upsert(_layout("515", "SameTab"))
    assert store.get("514") is not None
    assert store.get("515") is not None
    assert store.get("514").logical_matrix_name == store.get("515").logical_matrix_name
