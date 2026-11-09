from __future__ import annotations

from collections.abc import Callable
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
from src.application.matrix_automation.ports import (
    MatrixPriceSnapshotStore,
    SnackMachineLayoutStore,
)
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_planogram import (
    PlanogramAnchorCell,
    PlanogramValidationError,
    SnackPlanogramMerge,
    drop_absorbed_merge_anchors,
    filter_merges_in_bounds,
    project_planogram_cells,
    validate_planogram,
    validate_planogram_shrink,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.ids import MachineId


class SnackLayoutCommandRejected(Exception):
    @beartype
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@beartype
@dataclass(frozen=True, slots=True)
class SaveSnackLayoutInput:
    machine_code: str
    matrix_multiplier: Decimal
    auto_sync_enabled: bool
    shelf_count: int
    slots_per_shelf: int
    merges: tuple[SnackPlanogramMerge, ...]
    anchors: tuple[PlanogramAnchorCell, ...]
    actor_telegram_user_id: int


@beartype
@dataclass(slots=True)
class SaveSnackLayout:
    layouts: SnackMachineLayoutStore
    audit_stores: MasterDataStores
    now_factory: Callable[[], datetime]
    known_product_codes: frozenset[str]
    matrix_multiplier_min: Decimal
    matrix_multiplier_max: Decimal
    snapshots: MatrixPriceSnapshotStore
    archived_product_codes: frozenset[str] = frozenset()
    products: DomainProductStore | None = None

    @beartype
    def execute(self, input: SaveSnackLayoutInput) -> None:
        if not (
            self.matrix_multiplier_min <= input.matrix_multiplier <= self.matrix_multiplier_max
        ):
            raise SnackLayoutCommandRejected(
                f"matrix_multiplier {input.matrix_multiplier} out of bounds "
                f"[{self.matrix_multiplier_min}, {self.matrix_multiplier_max}]",
                code="matrix_multiplier_out_of_bounds",
            )

        existing = self.layouts.get(input.machine_code)
        if existing is not None:
            try:
                validate_planogram_shrink(
                    old_shelf_count=existing.shelf_count,
                    old_slots_per_shelf=existing.slots_per_shelf,
                    new_shelf_count=input.shelf_count,
                    new_slots_per_shelf=input.slots_per_shelf,
                    anchors=input.anchors,
                )
            except PlanogramValidationError as exc:
                raise SnackLayoutCommandRejected(exc.message, code=exc.code) from exc

        merges = filter_merges_in_bounds(
            input.merges,
            shelf_count=input.shelf_count,
            slots_per_shelf=input.slots_per_shelf,
        )

        try:
            validate_planogram(
                shelf_count=input.shelf_count,
                slots_per_shelf=input.slots_per_shelf,
                merges=merges,
            )
        except PlanogramValidationError as exc:
            raise SnackLayoutCommandRejected(exc.message, code=exc.code) from exc

        anchors_for_projection = drop_absorbed_merge_anchors(input.anchors, merges)
        try:
            projected = project_planogram_cells(anchors=anchors_for_projection)
        except PlanogramValidationError as exc:
            raise SnackLayoutCommandRejected(exc.message, code=exc.code) from exc

        cells = self._normalize_cells(projected, existing=existing)

        logical_matrix_name = (
            existing.logical_matrix_name if existing is not None else input.machine_code
        )
        if input.auto_sync_enabled and not self.snapshots.has_unit_snapshot(
            machine_code=input.machine_code,
            logical_matrix_name=logical_matrix_name,
        ):
            raise SnackLayoutCommandRejected(
                "auto_sync requires a successful apply snapshot",
                code="auto_sync_requires_apply",
            )
        self.layouts.upsert(
            SnackMachineLayout(
                machine_code=input.machine_code,
                logical_matrix_name=logical_matrix_name,
                matrix_multiplier=input.matrix_multiplier,
                auto_sync_enabled=input.auto_sync_enabled,
                cells=cells,
                shelf_count=input.shelf_count,
                slots_per_shelf=input.slots_per_shelf,
                merges=merges,
            )
        )
        now = self.now_factory()
        self.audit_stores.audit.append(
            MasterDataAuditRecord(
                at=now,
                actor_telegram_user_id=input.actor_telegram_user_id,
                command="save_snack_layout",
                payload={
                    "machine_code": input.machine_code,
                    "matrix_multiplier": str(input.matrix_multiplier),
                    "auto_sync_enabled": str(input.auto_sync_enabled),
                    "cell_count": str(len(cells)),
                },
            )
        )

    @beartype
    def _normalize_cells(
        self,
        projected: tuple[SnackMachineLayoutCell, ...],
        *,
        existing: SnackMachineLayout | None,
    ) -> tuple[SnackMachineLayoutCell, ...]:
        legacy_archived = self._legacy_archived_codes(existing)
        cells: list[SnackMachineLayoutCell] = []
        for cell in projected:
            domain_id = (cell.domain_product_id or "").strip() or None
            if domain_id is not None:
                product = self.products.get(domain_id) if self.products is not None else None
                if product is None:
                    raise SnackLayoutCommandRejected(
                        f"unknown domain_product_id {domain_id!r}",
                        code="unknown_domain_product_id",
                    )
                catalog_code = (product.catalog_code or "").strip() or None
                if (
                    catalog_code is not None
                    and catalog_code in self.archived_product_codes
                    and catalog_code not in legacy_archived
                ):
                    raise SnackLayoutCommandRejected(
                        f"archived product_code {catalog_code!r}",
                        code="archived_product_code",
                    )
                cells.append(
                    SnackMachineLayoutCell(
                        line_number=cell.line_number,
                        product_code=None,
                        shelf_index=cell.shelf_index,
                        slot_index=cell.slot_index,
                        domain_product_id=domain_id,
                    )
                )
                continue

            if cell.product_code is None:
                cells.append(cell)
                continue

            mapped_id: str | None = None
            if self.products is not None:
                mapped = self.products.get_by_catalog_code(cell.product_code)
                if mapped is not None:
                    mapped_id = mapped.domain_product_id
                    catalog_code = (mapped.catalog_code or "").strip() or None
                    if (
                        catalog_code is not None
                        and catalog_code in self.archived_product_codes
                        and catalog_code not in legacy_archived
                    ):
                        raise SnackLayoutCommandRejected(
                            f"archived product_code {catalog_code!r}",
                            code="archived_product_code",
                        )
                    cells.append(
                        SnackMachineLayoutCell(
                            line_number=cell.line_number,
                            product_code=None,
                            shelf_index=cell.shelf_index,
                            slot_index=cell.slot_index,
                            domain_product_id=mapped_id,
                        )
                    )
                    continue

            if cell.product_code not in self.known_product_codes:
                raise SnackLayoutCommandRejected(
                    f"unknown product_code {cell.product_code!r}",
                    code="unknown_product_code",
                )
            if (
                cell.product_code in self.archived_product_codes
                and cell.product_code not in legacy_archived
            ):
                raise SnackLayoutCommandRejected(
                    f"archived product_code {cell.product_code!r}",
                    code="archived_product_code",
                )
            cells.append(cell)
        return tuple(cells)

    @beartype
    def _legacy_archived_codes(
        self,
        existing: SnackMachineLayout | None,
    ) -> frozenset[str]:
        if existing is None:
            return frozenset()
        codes: set[str] = set()
        for cell in existing.cells:
            if cell.product_code is not None and cell.product_code in self.archived_product_codes:
                codes.add(cell.product_code)
            domain_id = (cell.domain_product_id or "").strip() or None
            if domain_id is not None and self.products is not None:
                product = self.products.get(domain_id)
                if product is not None:
                    catalog_code = (product.catalog_code or "").strip() or None
                    if catalog_code is not None and catalog_code in self.archived_product_codes:
                        codes.add(catalog_code)
        return frozenset(codes)


@beartype
@dataclass(frozen=True, slots=True)
class CopySnackLayoutInput:
    source_machine_code: str
    dest_machine_code: str
    actor_telegram_user_id: int


@beartype
@dataclass(slots=True)
class CopySnackLayout:
    layouts: SnackMachineLayoutStore
    machines: MasterMachineStore
    audit_stores: MasterDataStores
    now_factory: Callable[[], datetime]
    known_product_codes: frozenset[str]

    @beartype
    def execute(self, input: CopySnackLayoutInput) -> None:
        if not input.source_machine_code.strip():
            raise SnackLayoutCommandRejected(
                "source_machine_code must be non-empty",
                code="empty_copy_source",
            )
        if input.source_machine_code == input.dest_machine_code:
            raise SnackLayoutCommandRejected(
                "source and dest machine_code must differ",
                code="copy_same_machine",
            )

        source_machine = self.machines.get(MachineId(input.source_machine_code))
        if source_machine is None or source_machine.kind is not MachineKind.SNACK:
            raise SnackLayoutCommandRejected(
                f"source machine {input.source_machine_code!r} is not snack",
                code="source_not_snack",
            )

        dest_machine = self.machines.get(MachineId(input.dest_machine_code))
        if dest_machine is None or dest_machine.kind is not MachineKind.SNACK:
            raise SnackLayoutCommandRejected(
                f"dest machine {input.dest_machine_code!r} is not snack",
                code="dest_not_snack",
            )

        source_layout = self.layouts.get(input.source_machine_code)
        if source_layout is None:
            raise SnackLayoutCommandRejected(
                f"source layout missing for {input.source_machine_code!r}",
                code="source_layout_missing",
            )

        for cell in source_layout.cells:
            if cell.product_code is None:
                continue
            if cell.product_code not in self.known_product_codes:
                raise SnackLayoutCommandRejected(
                    f"unknown product_code {cell.product_code!r}",
                    code="unknown_product_code",
                )

        dest_layout = self.layouts.get(input.dest_machine_code)
        dest_name = (
            dest_layout.logical_matrix_name if dest_layout is not None else input.dest_machine_code
        )
        self.layouts.upsert(
            SnackMachineLayout(
                machine_code=input.dest_machine_code,
                logical_matrix_name=dest_name,
                matrix_multiplier=source_layout.matrix_multiplier,
                auto_sync_enabled=source_layout.auto_sync_enabled,
                cells=source_layout.cells,
                shelf_count=source_layout.shelf_count,
                slots_per_shelf=source_layout.slots_per_shelf,
                merges=source_layout.merges,
            )
        )
        now = self.now_factory()
        self.audit_stores.audit.append(
            MasterDataAuditRecord(
                at=now,
                actor_telegram_user_id=input.actor_telegram_user_id,
                command="copy_snack_layout",
                payload={
                    "source_machine_code": input.source_machine_code,
                    "dest_machine_code": input.dest_machine_code,
                },
            )
        )
