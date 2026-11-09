from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.layout_parse import layouts_to_parse_state
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)


def test_apply_layout_allows_duplicate_logical_matrix_name() -> None:
    store = InMemorySnackMachineLayoutStore()
    store.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="Twin",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, "A"),),
        )
    )
    store.upsert(
        SnackMachineLayout(
            machine_code="515",
            logical_matrix_name="Twin",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=True,
            cells=(SnackMachineLayoutCell(1, "B"),),
        )
    )
    state = layouts_to_parse_state(store.list_all())
    assert len(state.enabled_matrices) == 2
    codes = {m.machine_codes for m in state.enabled_matrices}
    assert codes == {("514",), ("515",)}


def test_auto_sync_disabled_counted_per_machine() -> None:
    store = InMemorySnackMachineLayoutStore()
    store.upsert(
        SnackMachineLayout(
            machine_code="514",
            logical_matrix_name="A",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(),
        )
    )
    store.upsert(
        SnackMachineLayout(
            machine_code="515",
            logical_matrix_name="B",
            matrix_multiplier=Decimal("1"),
            auto_sync_enabled=False,
            cells=(),
        )
    )
    state = layouts_to_parse_state(store.list_all())
    assert state.enabled_matrices == ()
    assert state.auto_sync_disabled_matrices == 2
