from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.master_data import MasterDataAuditRecord, MasterDataStores
from src.application.matrix_automation.matrix_sku_catalog import (
    MatrixSkuCatalogEntry,
    resolve_product_multiplier,
)
from src.application.matrix_automation.ports import MatrixSkuCatalogStore

_LOGGER = logging.getLogger(__name__)


class MatrixSkuCommandRejected(Exception):
    @beartype
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@beartype
@dataclass(frozen=True, slots=True)
class EnrollMatrixSkuInput:
    product_code: str
    capacity: int
    product_multiplier: Decimal | None
    actor_telegram_user_id: int


@beartype
@dataclass(slots=True)
class EnrollMatrixSku:
    catalog: MatrixSkuCatalogStore
    audit_stores: MasterDataStores
    now_factory: Callable[[], datetime]
    sellable_by_code: Mapping[str, tuple[str, str]]  # name, entity_kind
    product_multiplier_min: Decimal
    product_multiplier_max: Decimal

    @beartype
    def execute(self, input: EnrollMatrixSkuInput) -> None:
        if self.catalog.get(input.product_code) is not None:
            raise MatrixSkuCommandRejected(
                f"product_code {input.product_code!r} already enrolled",
                code="duplicate_product_code",
            )
        sellable = self.sellable_by_code.get(input.product_code)
        if sellable is None:
            raise MatrixSkuCommandRejected(
                f"unknown sellable code {input.product_code!r}",
                code="unknown_sellable_code",
            )
        name, kind = sellable
        if kind != "product":
            raise MatrixSkuCommandRejected(
                f"sellable {input.product_code!r} is not product",
                code="sellable_not_product",
            )
        if input.capacity < 0:
            raise MatrixSkuCommandRejected(
                "capacity must be >= 0",
                code="invalid_capacity",
            )
        if not name.strip():
            raise MatrixSkuCommandRejected(
                "display_name must be non-empty",
                code="invalid_display_name",
            )
        multiplier = resolve_product_multiplier(input.product_multiplier)
        if not (self.product_multiplier_min <= multiplier <= self.product_multiplier_max):
            raise MatrixSkuCommandRejected(
                f"product_multiplier {multiplier} out of bounds",
                code="product_multiplier_out_of_bounds",
            )
        self.catalog.upsert(
            MatrixSkuCatalogEntry(
                product_code=input.product_code,
                display_name=name.strip(),
                capacity=input.capacity,
                product_multiplier=multiplier,
            )
        )
        self.audit_stores.audit.append(
            MasterDataAuditRecord(
                at=self.now_factory(),
                actor_telegram_user_id=input.actor_telegram_user_id,
                command="enroll_matrix_sku",
                payload={"product_code": input.product_code},
            )
        )


@beartype
@dataclass(frozen=True, slots=True)
class SaveMatrixSkuInput:
    product_code: str
    display_name: str
    capacity: int
    product_multiplier: Decimal
    actor_telegram_user_id: int


@beartype
@dataclass(slots=True)
class SaveMatrixSku:
    catalog: MatrixSkuCatalogStore
    audit_stores: MasterDataStores
    now_factory: Callable[[], datetime]
    product_multiplier_min: Decimal
    product_multiplier_max: Decimal

    @beartype
    def execute(self, input: SaveMatrixSkuInput) -> None:
        if self.catalog.get(input.product_code) is None:
            raise MatrixSkuCommandRejected(
                f"product_code {input.product_code!r} not enrolled",
                code="missing_product_code",
            )
        if input.capacity < 0:
            raise MatrixSkuCommandRejected(
                "capacity must be >= 0",
                code="invalid_capacity",
            )
        if not input.display_name.strip():
            raise MatrixSkuCommandRejected(
                "display_name must be non-empty",
                code="invalid_display_name",
            )
        if not (
            self.product_multiplier_min <= input.product_multiplier <= self.product_multiplier_max
        ):
            raise MatrixSkuCommandRejected(
                f"product_multiplier {input.product_multiplier} out of bounds",
                code="product_multiplier_out_of_bounds",
            )
        self.catalog.upsert(
            MatrixSkuCatalogEntry(
                product_code=input.product_code,
                display_name=input.display_name.strip(),
                capacity=input.capacity,
                product_multiplier=input.product_multiplier,
            )
        )
        self.audit_stores.audit.append(
            MasterDataAuditRecord(
                at=self.now_factory(),
                actor_telegram_user_id=input.actor_telegram_user_id,
                command="save_matrix_sku",
                payload={"product_code": input.product_code},
            )
        )


@beartype
@dataclass(frozen=True, slots=True)
class BulkSaveMatrixSkuRow:
    product_code: str
    display_name: str
    capacity: int
    product_multiplier: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class BulkSaveMatrixSkuInput:
    rows: tuple[BulkSaveMatrixSkuRow, ...]
    allowed_codes: frozenset[str]
    actor_telegram_user_id: int


@beartype
@dataclass(slots=True)
class BulkSaveMatrixSku:
    catalog: MatrixSkuCatalogStore
    audit_stores: MasterDataStores
    now_factory: Callable[[], datetime]
    product_multiplier_min: Decimal
    product_multiplier_max: Decimal

    @beartype
    def execute(self, input: BulkSaveMatrixSkuInput) -> None:
        validated: list[tuple[str, BulkSaveMatrixSkuRow]] = []
        for row in input.rows:
            code = row.product_code.strip()
            self._validate_bulk_row(row, code=code, allowed_codes=input.allowed_codes)
            validated.append((code, row))
        applied_count = 0
        last_applied_code: str | None = None
        try:
            for code, row in validated:
                self._persist_row(
                    code,
                    row,
                    actor_telegram_user_id=input.actor_telegram_user_id,
                )
                last_applied_code = code
                applied_count += 1
        except Exception:
            if last_applied_code is not None:
                _LOGGER.error(
                    "bulk_save_matrix_sku_partial",
                    extra={
                        "last_applied_code": last_applied_code,
                        "applied_count": applied_count,
                    },
                )
            raise

    @beartype
    def _validate_bulk_row(
        self,
        row: BulkSaveMatrixSkuRow,
        *,
        code: str,
        allowed_codes: frozenset[str],
    ) -> None:
        if code not in allowed_codes:
            raise MatrixSkuCommandRejected(
                f"product_code {code!r} not in snack assortment",
                code="unknown_snack_code",
            )
        if row.capacity < 0:
            raise MatrixSkuCommandRejected(
                "capacity must be >= 0",
                code="invalid_capacity",
            )
        name = row.display_name.strip()
        if not name:
            raise MatrixSkuCommandRejected(
                "display_name must be non-empty",
                code="invalid_display_name",
            )
        if not (
            self.product_multiplier_min <= row.product_multiplier <= self.product_multiplier_max
        ):
            raise MatrixSkuCommandRejected(
                f"product_multiplier {row.product_multiplier} out of bounds",
                code="product_multiplier_out_of_bounds",
            )

    @beartype
    def _persist_row(
        self,
        code: str,
        row: BulkSaveMatrixSkuRow,
        *,
        actor_telegram_user_id: int,
    ) -> None:
        name = row.display_name.strip()
        self.catalog.upsert(
            MatrixSkuCatalogEntry(
                product_code=code,
                display_name=name,
                capacity=row.capacity,
                product_multiplier=row.product_multiplier,
            )
        )
        self.audit_stores.audit.append(
            MasterDataAuditRecord(
                at=self.now_factory(),
                actor_telegram_user_id=actor_telegram_user_id,
                command="save_matrix_sku",
                payload={"product_code": code},
            )
        )
