from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from beartype import beartype

SkuPriceOutcome = Literal[
    "applied",
    "kept_previous",
    "skipped_no_baseline",
    "blocked_empty",
    "product_swap_blocked",
]

DeployStatus = Literal["applied", "skipped"]

MatrixDeployApplyStatus = Literal["applied", "failed"]
MatrixDeployFailureReason = Literal[
    "upload_failed",
    "bind_failed",
    "load_timeout",
    "apply_timeout",
    "machine_not_found_in_kit",
    "ambiguous_machine_code",
    "kit_machine_lookup_failed",
]


@beartype
@dataclass(frozen=True, slots=True)
class PurchaseAttributesFetchResult:
    attributes: dict[str, tuple[str, int]]
    cards_found: int
    supply_http_failed: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MatrixDeployResult:
    logical_matrix_name: str
    machine_code: str
    status: MatrixDeployApplyStatus
    reason: MatrixDeployFailureReason | None
    kit_matrix_id: int | None = None
    vending_machine_id: int | None = None
    kit_matrix_name: str | None = None


@dataclass(frozen=True, slots=True)
class BlockedProductRef:
    product_name: str
    product_code: str | None


@dataclass(frozen=True, slots=True)
class BlockedMatrixEntry:
    logical_matrix_name: str
    deploy_reason: str
    detail: str
    products: tuple[BlockedProductRef, ...]
    machine_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProductBlock:
    product_name: str | None
    product_code: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class MatrixCatalogCell:
    line_number: int
    product_name: str
    product_code: str | None


@dataclass(frozen=True, slots=True)
class EnabledLogicalMatrix:
    logical_matrix_name: str
    machine_codes: tuple[str, ...]
    matrix_multiplier: Decimal
    cells: tuple[MatrixCatalogCell, ...]


@dataclass(frozen=True, slots=True)
class MatrixParseState:
    enabled_matrices: tuple[EnabledLogicalMatrix, ...]
    blocked_matrices: tuple[BlockedMatrixEntry, ...]
    product_block_map: dict[str, ProductBlock]
    auto_sync_disabled_matrices: int


@dataclass(frozen=True, slots=True)
class MatrixDeployPayloadLine:
    line_number: int
    product_code: str | None
    product_name: str
    deploy_price: Decimal
    capacity: int
    outcome: SkuPriceOutcome
    reason: str | None
    strong_price_increase: bool
    desired_product: str | None = None
    baseline_price: Decimal | None = None
    purchase_price: Decimal | None = None
    calculated_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class MatrixDeployPayload:
    logical_matrix_name: str
    machine_code: str
    matrix_multiplier: str
    lines: tuple[MatrixDeployPayloadLine, ...]


@dataclass(frozen=True, slots=True)
class SkuStats:
    applied: int = 0
    kept_previous: int = 0
    skipped_no_baseline: int = 0
    strong_price_increase: int = 0
    blocked_empty: int = 0
    product_swap_blocked: int = 0


@dataclass(frozen=True, slots=True)
class MatrixDeploySkippedUnit:
    logical_matrix_name: str
    machine_code: str
    deploy_status: DeployStatus
    deploy_reason: str
    sku_stats: SkuStats | None = None
    lines: tuple[MatrixDeployPayloadLine, ...] = ()


@dataclass(frozen=True, slots=True)
class BuildMatrixDeployResult:
    payloads: tuple[MatrixDeployPayload, ...]
    skipped_units: tuple[MatrixDeploySkippedUnit, ...]


@dataclass(frozen=True, slots=True)
class SnapshotLineRecord:
    line_number: int
    product_code: str | None
    product_name: str
    capacity: int
    purchase_price: str | None
    calculated_price: str | None
    deploy_price: str
    outcome: SkuPriceOutcome
    reason: str | None
    strong_price_increase: bool


@dataclass(frozen=True, slots=True)
class PriceSnapshotDocument:
    job_id: str
    machine_code: str
    logical_matrix_name: str
    recorded_at: str
    lines: tuple[SnapshotLineRecord, ...]
