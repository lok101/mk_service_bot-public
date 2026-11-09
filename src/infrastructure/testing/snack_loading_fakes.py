from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from beartype import beartype

from src.application.snack_loading.ports import (
    CopiedSnackInventoryForm,
    InventoryFormCell,
    KitMatrixDeployMapRow,
    KitMatrixDeployMapStore,
    RegisteredSnackInventoryForm,
    SnackInventoryFormFactory,
    SnackInventoryFormMode,
    SnackInventoryFormRegistry,
    SnackMachineStockStore,
)
from src.domain.snack_loading import SnackMachineStock, SnackStockConcurrencyError
from src.domain.snack_loading.events import SnackStockEvent


@beartype
@dataclass(slots=True)
class InMemorySnackMachineStockStore(SnackMachineStockStore):
    _streams: dict[str, list[SnackStockEvent]] = field(default_factory=dict)

    @beartype
    def load(self, machine_code: str) -> SnackMachineStock | None:
        stream = self._streams.get(machine_code)
        if stream is None:
            return None
        return SnackMachineStock.rehydrate(machine_code=machine_code, events=stream)

    @beartype
    def save(self, stock: SnackMachineStock) -> None:
        stream = self._streams.setdefault(stock.machine_code, [])
        if len(stream) != stock.loaded_version:
            raise SnackStockConcurrencyError(machine_code=stock.machine_code)
        pending = stock.pull_events()
        if not pending:
            return
        stream.extend(pending)


@beartype
@dataclass(slots=True)
class InMemoryKitMatrixDeployMapStore(KitMatrixDeployMapStore):
    _rows: dict[int, KitMatrixDeployMapRow] = field(default_factory=dict)

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
    ) -> None:
        self._rows[kit_matrix_id] = KitMatrixDeployMapRow(
            kit_matrix_id=kit_matrix_id,
            logical_matrix_name=logical_matrix_name,
            machine_code=machine_code,
            vending_machine_id=vending_machine_id,
            kit_matrix_name=kit_matrix_name,
            applied_at=applied_at if applied_at is not None else datetime.now(UTC),
        )

    @beartype
    def get(self, kit_matrix_id: int) -> KitMatrixDeployMapRow | None:
        return self._rows.get(kit_matrix_id)


@beartype
@dataclass(slots=True)
class InMemorySnackInventoryFormRegistry(SnackInventoryFormRegistry):
    _entries: dict[tuple[str, SnackInventoryFormMode, str], RegisteredSnackInventoryForm] = field(
        default_factory=dict,
    )

    @beartype
    def get(
        self,
        machine_code: str,
        mode: SnackInventoryFormMode,
        fingerprint: str,
    ) -> RegisteredSnackInventoryForm | None:
        return self._entries.get((machine_code, mode, fingerprint))

    @beartype
    def put(
        self,
        machine_code: str,
        mode: SnackInventoryFormMode,
        fingerprint: str,
        *,
        form_id: str,
        form_url: str,
    ) -> None:
        self._entries[(machine_code, mode, fingerprint)] = RegisteredSnackInventoryForm(
            form_id=form_id,
            form_url=form_url,
        )


@beartype
@dataclass(slots=True)
class FakeSnackInventoryFormFactory(SnackInventoryFormFactory):
    copy_calls: int = 0
    _next_id: int = 1

    @beartype
    def copy_template_and_build_questions(
        self,
        *,
        template_id: str,
        cells: Sequence[InventoryFormCell],
        qty_max: int,
    ) -> CopiedSnackInventoryForm:
        del template_id, cells, qty_max
        self.copy_calls += 1
        form_id = f"form-copied-{self._next_id}"
        self._next_id += 1
        return CopiedSnackInventoryForm(
            form_id=form_id,
            form_url=f"https://forms.example/{form_id}",
        )


@beartype
@dataclass(slots=True)
class FakeSnackInventoryFormsConfig:
    incomplete: bool = False

    @beartype
    def require_snack_inventory_forms(self) -> None:
        if self.incomplete:
            raise ValueError(
                "Snack inventory Forms settings incomplete: SNACK_INVENTORY_FORM_TOKEN_ENTRY_ID",
            )


@beartype
@dataclass(slots=True)
class FakeSnackInventoryCellsSource:
    cells_by_machine: dict[str, Sequence[InventoryFormCell]] = field(default_factory=dict)

    @beartype
    def list_cells(self, machine_code: str) -> Sequence[InventoryFormCell]:
        return tuple(self.cells_by_machine.get(machine_code, ()))
