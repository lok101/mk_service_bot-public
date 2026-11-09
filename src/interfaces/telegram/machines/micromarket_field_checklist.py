from __future__ import annotations

from typing import Any

from beartype import beartype

_CHECKLIST_STEP_KEY = "mm_field_checklist_step"
_CHECKLIST_MACHINE_KEY = "mm_field_checklist_machine_id"

CHECKLIST_LOCKED_INVENTORY_MESSAGE = "Сначала отметьте шаги 1–3."
CHECKLIST_STEP_LOCKED_MESSAGE = "Сначала предыдущий шаг."

# dialog_data: plain dict in production; MagicMock in handler tests (no MutableMapping).


def get_checklist_step(dialog_data: Any) -> int:
    raw = dialog_data.get(_CHECKLIST_STEP_KEY, 0)
    if isinstance(raw, int) and 0 <= raw <= 3:
        return raw
    return 0


def clear_checklist_progress(dialog_data: Any) -> None:
    dialog_data.pop(_CHECKLIST_STEP_KEY, None)
    dialog_data.pop(_CHECKLIST_MACHINE_KEY, None)


def sync_checklist_machine(
    dialog_data: Any,
    *,
    machine_id: str,
) -> None:
    """Reset checklist when selected machine changes."""
    previous = dialog_data.get(_CHECKLIST_MACHINE_KEY)
    if previous is not None and previous != machine_id:
        clear_checklist_progress(dialog_data)
    dialog_data[_CHECKLIST_MACHINE_KEY] = machine_id


def try_advance_checklist(
    dialog_data: Any,
    *,
    target_step: int,
) -> bool:
    """Advance to target_step (1..3) when current == target_step - 1. One-way."""
    if target_step not in (1, 2, 3):
        return False
    current = get_checklist_step(dialog_data)
    if current == target_step:
        return True  # already done — no-op success
    if current != target_step - 1:
        return False
    dialog_data[_CHECKLIST_STEP_KEY] = target_step
    return True


@beartype
def inventory_unlocked_by_checklist(
    *,
    checklist_step: int,
    inventory_already_done: bool,
) -> bool:
    return inventory_already_done or checklist_step >= 3
