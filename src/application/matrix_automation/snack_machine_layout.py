from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation.snack_planogram import (
    SNACK_PLANOGRAM_DEFAULT_SHELF_COUNT,
    SNACK_PLANOGRAM_DEFAULT_SLOTS_PER_SHELF,
    SnackPlanogramMerge,
)


@beartype
@dataclass(frozen=True, slots=True)
class SnackMachineLayoutCell:
    line_number: int
    product_code: str | None
    shelf_index: int | None = None
    slot_index: int | None = None
    domain_product_id: str | None = None


@beartype
@dataclass(frozen=True, slots=True)
class SnackMachineLayout:
    machine_code: str
    logical_matrix_name: str
    matrix_multiplier: Decimal
    auto_sync_enabled: bool
    cells: tuple[SnackMachineLayoutCell, ...]
    shelf_count: int = SNACK_PLANOGRAM_DEFAULT_SHELF_COUNT
    slots_per_shelf: int = SNACK_PLANOGRAM_DEFAULT_SLOTS_PER_SHELF
    merges: tuple[SnackPlanogramMerge, ...] = ()
