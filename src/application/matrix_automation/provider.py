from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation.layout_parse import enabled_matrix_from_layout
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    EnabledLogicalMatrix,
    MatrixParseState,
    ProductBlock,
)
from src.application.matrix_automation.sheets.matrix_catalog import parse_matrix_catalog_tab
from src.application.matrix_automation.sheets.product_multipliers import (
    parse_product_multipliers_sheet,
)
from src.application.matrix_automation.snack_machine_layout import SnackMachineLayout
from src.application.reference_data import ReferenceDataSourceId


@beartype
@dataclass(slots=True)
class MatrixReferenceDataProvider:
    product_multiplier_min: Decimal
    product_multiplier_max: Decimal
    matrix_multiplier_min: Decimal
    matrix_multiplier_max: Decimal
    _name_to_code: dict[str, str] = field(default_factory=dict, repr=False)
    _product_multipliers: dict[str, Decimal] = field(default_factory=dict, repr=False)
    _product_block_map: dict[str, ProductBlock] = field(default_factory=dict, repr=False)
    _enabled_matrices: list[EnabledLogicalMatrix] = field(default_factory=list, repr=False)
    _blocked_matrices: list[BlockedMatrixEntry] = field(default_factory=list, repr=False)
    _auto_sync_disabled: int = field(default=0, repr=False)
    _catalog_tab_titles: list[str] = field(default_factory=list, repr=False)
    _pending_catalog_rows: dict[str, list[list[str]]] = field(default_factory=dict, repr=False)

    @property
    def product_multipliers(self) -> dict[str, Decimal]:
        return dict(self._product_multipliers)

    @property
    def name_to_code(self) -> dict[str, str]:
        return dict(self._name_to_code)

    @beartype
    def set_name_to_code(self, name_to_code: dict[str, str]) -> None:
        self._name_to_code = dict(name_to_code)

    @beartype
    def apply_rows(self, source_id: ReferenceDataSourceId, rows: list[list[str]]) -> None:
        if source_id is ReferenceDataSourceId.PRODUCT_MULTIPLIERS:
            multipliers_result = parse_product_multipliers_sheet(
                rows,
                min_bound=self.product_multiplier_min,
                max_bound=self.product_multiplier_max,
            )
            self._product_multipliers = multipliers_result.multipliers
            for code, block in multipliers_result.product_block_map.items():
                self._product_block_map[code] = block
            return
        raise ValueError(f"unsupported matrix source_id: {source_id}")

    @beartype
    def apply_catalog_tab(self, logical_matrix_name: str, rows: list[list[str]]) -> None:
        trimmed = logical_matrix_name.strip()
        if trimmed in self._catalog_tab_titles:
            msg = f"duplicate logical_matrix_name: {trimmed}"
            raise ValueError(msg)
        self._catalog_tab_titles.append(trimmed)
        parsed = parse_matrix_catalog_tab(
            rows,
            logical_matrix_name=logical_matrix_name,
            name_to_code=self._name_to_code,
            product_block_map=self._product_block_map,
            matrix_multiplier_min=self.matrix_multiplier_min,
            matrix_multiplier_max=self.matrix_multiplier_max,
        )
        if parsed.auto_sync_disabled:
            self._auto_sync_disabled += 1
            return
        if parsed.blocked is not None:
            self._blocked_matrices.append(parsed.blocked)
            return
        if parsed.enabled is not None:
            self._enabled_matrices.append(parsed.enabled)

    @beartype
    def apply_snack_layout(self, layout: SnackMachineLayout) -> None:
        if not layout.auto_sync_enabled:
            self._auto_sync_disabled += 1
            return
        self._enabled_matrices.append(enabled_matrix_from_layout(layout))

    @beartype
    def build_parse_state(self) -> MatrixParseState:
        return MatrixParseState(
            enabled_matrices=tuple(self._enabled_matrices),
            blocked_matrices=tuple(self._blocked_matrices),
            product_block_map=dict(self._product_block_map),
            auto_sync_disabled_matrices=self._auto_sync_disabled,
        )

    @beartype
    def reset_catalog_parse(self) -> None:
        self._enabled_matrices.clear()
        self._blocked_matrices.clear()
        self._auto_sync_disabled = 0
        self._catalog_tab_titles.clear()
        self._pending_catalog_rows.clear()
