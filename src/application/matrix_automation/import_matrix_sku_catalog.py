from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.master_data import MasterDataAuditRecord, MasterDataStores
from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.ports import (
    MatrixSkuCatalogStore,
    SnackMachineLayoutStore,
)


@beartype
@dataclass(frozen=True, slots=True)
class ImportMatrixSkuCatalogInput:
    actor_telegram_user_id: int


@beartype
@dataclass(frozen=True, slots=True)
class ImportMatrixSkuCatalogResult:
    imported_count: int
    skipped_codes: tuple[str, ...]
    skipped_existing_codes: tuple[str, ...]


@beartype
@dataclass(slots=True)
class ImportMatrixSkuCatalog:
    catalog: MatrixSkuCatalogStore
    layouts: SnackMachineLayoutStore | None
    audit_stores: MasterDataStores
    now_factory: Callable[[], datetime]
    multipliers: Mapping[str, Decimal]
    sheet_names: Mapping[str, str]
    ms_by_code: Mapping[str, tuple[str, int]]
    product_multiplier_min: Decimal
    product_multiplier_max: Decimal

    @beartype
    def execute(self, input: ImportMatrixSkuCatalogInput) -> ImportMatrixSkuCatalogResult:
        codes: set[str] = set(self.multipliers)
        if self.layouts is not None:
            for layout in self.layouts.list_all():
                for cell in layout.cells:
                    if cell.product_code:
                        codes.add(cell.product_code)
        skipped: list[str] = []
        skipped_existing: list[str] = []
        imported = 0
        for code in sorted(codes):
            if self.catalog.get(code) is not None:
                skipped_existing.append(code)
                continue
            ms = self.ms_by_code.get(code)
            if ms is None:
                skipped.append(code)
                continue
            ms_name, capacity = ms
            if capacity <= 0:
                skipped.append(code)
                continue
            name = ms_name.strip() or self.sheet_names.get(code, "").strip()
            if not name:
                skipped.append(code)
                continue
            multiplier = self.multipliers.get(code, Decimal("1"))
            if not (self.product_multiplier_min <= multiplier <= self.product_multiplier_max):
                skipped.append(code)
                continue
            self.catalog.upsert(
                MatrixSkuCatalogEntry(
                    product_code=code,
                    display_name=name,
                    capacity=capacity,
                    product_multiplier=multiplier,
                )
            )
            imported += 1
        self.audit_stores.audit.append(
            MasterDataAuditRecord(
                at=self.now_factory(),
                actor_telegram_user_id=input.actor_telegram_user_id,
                command="import_matrix_sku_catalog",
                payload={
                    "imported_count": str(imported),
                    "skipped_codes": ",".join(skipped),
                    "skipped_existing_codes": ",".join(skipped_existing),
                },
            )
        )
        return ImportMatrixSkuCatalogResult(
            imported_count=imported,
            skipped_codes=tuple(skipped),
            skipped_existing_codes=tuple(skipped_existing),
        )
