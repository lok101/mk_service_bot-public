from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.master_data import (
    MachineKind,
    MasterDataAuditRecord,
    MasterDataStores,
    MasterMachineStore,
)
from src.application.matrix_automation.models import ProductBlock
from src.application.matrix_automation.ports import SnackMachineLayoutStore
from src.application.matrix_automation.sheets.matrix_catalog import (
    parse_catalog_tab_machine_codes,
    parse_matrix_catalog_tab,
)
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.domain.ids import MachineId

_logger = logging.getLogger(__name__)


@beartype
@dataclass(frozen=True, slots=True)
class ImportSnackLayoutsInput:
    tabs: Sequence[tuple[str, list[list[str]]]]
    actor_telegram_user_id: int


@beartype
@dataclass(frozen=True, slots=True)
class ImportSnackLayoutsResult:
    noop: bool
    skipped_codes: tuple[str, ...]
    skipped_existing_codes: tuple[str, ...] = ()
    blocked_tabs: tuple[str, ...] = ()
    conflict_codes: tuple[str, ...] = ()


@beartype
@dataclass(slots=True)
class ImportSnackLayouts:
    layouts: SnackMachineLayoutStore
    machines: MasterMachineStore
    audit_stores: MasterDataStores
    now_factory: Callable[[], datetime]
    name_to_code: dict[str, str]
    product_block_map: dict[str, ProductBlock]
    matrix_multiplier_min: Decimal
    matrix_multiplier_max: Decimal

    @beartype
    def execute(self, input: ImportSnackLayoutsInput) -> ImportSnackLayoutsResult:
        skipped: list[str] = []
        skipped_existing: list[str] = []
        blocked_tabs: list[str] = []
        conflict_codes: list[str] = []
        seen_in_run: set[str] = set()
        upserted = 0
        for title, rows in input.tabs:
            candidates, blocked_title = self._candidates_from_tab(title=title, rows=rows)
            if blocked_title is not None:
                blocked_tabs.append(blocked_title)
                continue
            for layout in candidates:
                code = layout.machine_code
                if code in seen_in_run:
                    conflict_codes.append(code)
                    continue
                seen_in_run.add(code)
                if self.layouts.get(code) is not None:
                    skipped_existing.append(code)
                    continue
                machine = self.machines.get(MachineId(code))
                if machine is None or machine.kind is not MachineKind.SNACK:
                    _logger.info(
                        "import_snack_layouts skip non-snack machine_code=%s",
                        code,
                    )
                    skipped.append(code)
                    continue
                self.layouts.upsert(layout)
                upserted += 1
        result = ImportSnackLayoutsResult(
            noop=upserted == 0,
            skipped_codes=tuple(skipped),
            skipped_existing_codes=tuple(skipped_existing),
            blocked_tabs=tuple(blocked_tabs),
            conflict_codes=tuple(conflict_codes),
        )
        self._write_audit(input=input, result=result)
        return result

    @beartype
    def _candidates_from_tab(
        self,
        *,
        title: str,
        rows: list[list[str]],
    ) -> tuple[list[SnackMachineLayout], str | None]:
        parsed = parse_matrix_catalog_tab(
            rows,
            logical_matrix_name=title,
            name_to_code=self.name_to_code,
            product_block_map=self.product_block_map,
            matrix_multiplier_min=self.matrix_multiplier_min,
            matrix_multiplier_max=self.matrix_multiplier_max,
        )
        if parsed.auto_sync_disabled:
            try:
                codes = parse_catalog_tab_machine_codes(rows)
            except ValueError:
                _logger.info(
                    "import_snack_layouts skip auto_sync_disabled tab=%s invalid H1",
                    title,
                )
                return [], title
            return [
                SnackMachineLayout(
                    machine_code=code,
                    logical_matrix_name=title.strip() or title,
                    matrix_multiplier=Decimal("1"),
                    auto_sync_enabled=False,
                    cells=(),
                )
                for code in codes
            ], None
        if parsed.blocked is not None:
            _logger.info(
                "import_snack_layouts skip blocked tab=%s detail=%s",
                title,
                parsed.blocked.detail,
            )
            return [], title
        if parsed.enabled is None:
            return [], None
        cells = tuple(
            SnackMachineLayoutCell(
                line_number=cell.line_number,
                product_code=cell.product_code,
            )
            for cell in parsed.enabled.cells
        )
        return [
            SnackMachineLayout(
                machine_code=code,
                logical_matrix_name=parsed.enabled.logical_matrix_name,
                matrix_multiplier=parsed.enabled.matrix_multiplier,
                auto_sync_enabled=True,
                cells=cells,
            )
            for code in parsed.enabled.machine_codes
        ], None

    @beartype
    def _write_audit(
        self,
        *,
        input: ImportSnackLayoutsInput,
        result: ImportSnackLayoutsResult,
    ) -> None:
        self.audit_stores.audit.append(
            MasterDataAuditRecord(
                at=self.now_factory(),
                actor_telegram_user_id=input.actor_telegram_user_id,
                command="import_snack_layouts",
                payload={
                    "noop": "true" if result.noop else "false",
                    "skipped_codes": ",".join(result.skipped_codes),
                    "skipped_existing_codes": ",".join(result.skipped_existing_codes),
                    "blocked_tabs": ",".join(result.blocked_tabs),
                    "conflict_codes": ",".join(result.conflict_codes),
                    "tab_count": str(len(input.tabs)),
                },
            )
        )
