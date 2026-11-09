from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from beartype import beartype

from src.application.snack_loading.loading_plan import SnackLoadingCellInput
from src.domain.snack_loading import SnackMachineStock

SnackInventoryFormMode = Literal["now", "as_of"]


@beartype
@dataclass(frozen=True, slots=True)
class InventoryFormCell:
    """One snack inventory qty question: identity + optional snapshot display name."""

    matrix_name: str
    line_number: int
    product_code: str
    product_name: str = ""


class SnackStoreResolveError(Exception):
    """Target store missing or outside SNACK_LOADING_WAREHOUSES_PATH."""


@beartype
@dataclass(frozen=True, slots=True)
class RegisteredSnackInventoryForm:
    form_id: str
    form_url: str


@beartype
@dataclass(frozen=True, slots=True)
class CopiedSnackInventoryForm:
    form_id: str
    form_url: str


@runtime_checkable
class SnackInventoryFormRegistry(Protocol):
    @beartype
    def get(
        self,
        machine_code: str,
        mode: SnackInventoryFormMode,
        fingerprint: str,
    ) -> RegisteredSnackInventoryForm | None: ...

    @beartype
    def put(
        self,
        machine_code: str,
        mode: SnackInventoryFormMode,
        fingerprint: str,
        *,
        form_id: str,
        form_url: str,
    ) -> None: ...


@runtime_checkable
class SnackInventoryFormFactory(Protocol):
    @beartype
    def copy_template_and_build_questions(
        self,
        *,
        template_id: str,
        cells: Sequence[InventoryFormCell],
        qty_max: int,
    ) -> CopiedSnackInventoryForm: ...


@runtime_checkable
class SnackInventoryFormsConfig(Protocol):
    """Process-gated snack Forms settings (wired from SnackLoadingSettings)."""

    @beartype
    def require_snack_inventory_forms(self) -> None: ...


@runtime_checkable
class SnackInventoryCellsSource(Protocol):
    """Inventory form cells from latest matrix price snapshots (excl. blocked/empty)."""

    @beartype
    def list_cells(self, machine_code: str) -> Sequence[InventoryFormCell]: ...


@runtime_checkable
class SnackMachineStockStore(Protocol):
    @beartype
    def load(self, machine_code: str) -> SnackMachineStock | None: ...

    @beartype
    def save(self, stock: SnackMachineStock) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class ResolvedSaleForReplay:
    source_id: str
    logical_matrix_name: str
    line_number: int
    product_code: str
    quantity: Decimal
    occurred_at: datetime
    resolve_status: str = "resolved"


@runtime_checkable
class SnackSalesAfterPort(Protocol):
    """Sales for inventory replay.

    AcceptSnackInventory deducts only rows with resolve_status ``resolved`` and
    ``occurred_at > after``. Adapters SHOULD pre-filter to resolved snack sales.
    """

    @beartype
    def query(
        self,
        machine_code: str,
        after: datetime,
    ) -> Sequence[ResolvedSaleForReplay]: ...


@beartype
@dataclass(frozen=True, slots=True)
class KitMatrixDeployMapRow:
    kit_matrix_id: int
    logical_matrix_name: str
    machine_code: str
    vending_machine_id: int | None
    kit_matrix_name: str | None
    applied_at: datetime | None = None


@runtime_checkable
class KitMatrixDeployMapStore(Protocol):
    @beartype
    def upsert(
        self,
        *,
        kit_matrix_id: int,
        logical_matrix_name: str,
        machine_code: str,
        vending_machine_id: int | None,
        kit_matrix_name: str | None,
        applied_at: datetime | None = None,
    ) -> None: ...

    @beartype
    def get(self, kit_matrix_id: int) -> KitMatrixDeployMapRow | None: ...


@runtime_checkable
class SnackSaleUnresolvedAlertNotifier(Protocol):
    @beartype
    def notify_unresolved_sales(self, *, count: int) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class NoOpSnackSaleUnresolvedAlertNotifier:
    @beartype
    def notify_unresolved_sales(self, *, count: int) -> None:
        del count


@runtime_checkable
class MatrixCatalogSync(Protocol):
    @beartype
    def sync(self) -> None: ...


@runtime_checkable
class SnackLoadingCellSource(Protocol):
    @beartype
    def list_plan_cells(self, machine_code: str) -> Sequence[SnackLoadingCellInput]: ...


@runtime_checkable
class SnackMainStockReader(Protocol):
    @beartype
    def available_by_product(self) -> dict[str, Decimal]: ...


@runtime_checkable
class SnackMoveClient(Protocol):
    @beartype
    def create_move(
        self,
        *,
        machine_code: str,
        positions: Sequence[tuple[str, Decimal]],
    ) -> str: ...


@beartype
@dataclass(frozen=True, slots=True)
class SnackLoadingRunRecord:
    run_id: str
    machine_code: str
    move_id: str
    increments: tuple[tuple[tuple[str, str, int], Decimal], ...]
    domain_applied: bool


@runtime_checkable
class SnackLoadingRunStore(Protocol):
    @beartype
    def get(self, run_id: str) -> SnackLoadingRunRecord | None: ...

    @beartype
    def save(self, record: SnackLoadingRunRecord) -> None: ...


@runtime_checkable
class SnackLoadingFailAfterMoveNotifier(Protocol):
    @beartype
    def notify_fail_after_move(
        self,
        *,
        machine_code: str,
        move_id: str,
        run_id: str,
    ) -> None: ...


@beartype
@dataclass(frozen=True, slots=True)
class NoOpSnackLoadingFailAfterMoveNotifier:
    @beartype
    def notify_fail_after_move(
        self,
        *,
        machine_code: str,
        move_id: str,
        run_id: str,
    ) -> None:
        del machine_code, move_id, run_id
