from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, TypeVar, runtime_checkable

from beartype import beartype

from src.domain.events import DomainEvent
from src.domain.ids import MachineId, TechnicianId
from src.domain.technician_warehouse import TechnicianWarehouse
from src.domain.technician_warehouse.events import (
    TechnicianWarehouseTransferFinalized,
    WarehouseEvent,
)

T = TypeVar("T")


@beartype
@dataclass(frozen=True, slots=True)
class ExternalWarehouseMoveLine:
    product_code: str
    product_name: str
    quantity: Decimal


@beartype
@dataclass(frozen=True, slots=True)
class ExternalWarehouseMove:
    document_id: str
    source_store_code: str
    target_store_code: str
    moment: datetime
    updated_at: datetime
    lines: tuple[ExternalWarehouseMoveLine, ...]
    applicable: bool = True


@beartype
@dataclass(frozen=True, slots=True)
class ReadMovesResult:
    moves: tuple[ExternalWarehouseMove, ...]
    skipped_unresolved: int


@beartype
@dataclass(frozen=True, slots=True)
class ImportedTransferRef:
    external_document_id: str
    content_hash: str


@beartype
@dataclass(frozen=True, slots=True)
class UnmatchedMsProduct:
    product_code: str
    product_name: str
    external_document_id: str


@runtime_checkable
class CatalogBaseQuantityResolver(Protocol):
    @beartype
    def try_resolve_line(
        self,
        *,
        product_code: str,
        moysklad_quantity: Decimal,
    ) -> tuple[str, Decimal] | None: ...

    @beartype
    def resolve_line(
        self,
        *,
        product_code: str,
        moysklad_quantity: Decimal,
    ) -> tuple[str, Decimal]: ...


@runtime_checkable
class TechnicianWarehouseTransferReader(Protocol):
    async def ensure_supply_store_codes_exist(self, codes: tuple[str, ...]) -> None: ...

    async def read_moves(
        self,
        *,
        technician_store_code: str,
        moment_from: datetime,
        moment_to: datetime,
    ) -> ReadMovesResult: ...


@runtime_checkable
class BorderProductGate(Protocol):
    """Hard-stop / ignore gate for MS product codes on the warehouse border."""

    @beartype
    def unregistered_among(self, codes: tuple[str, ...]) -> tuple[str, ...]: ...

    @beartype
    def is_ignored(self, code: str) -> bool: ...

    @beartype
    def note_unregistered(self, codes: tuple[str, ...]) -> None: ...


@runtime_checkable
class TechnicianWarehouseEventStore(Protocol):
    @beartype
    def append(
        self,
        technician_id: TechnicianId,
        expected_version: int,
        events: tuple[WarehouseEvent, ...],
    ) -> None: ...

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[WarehouseEvent]: ...

    @beartype
    def list_technician_ids(self) -> tuple[TechnicianId, ...]: ...

    @beartype
    def delete_all_for_technician(self, technician_id: TechnicianId) -> int:
        """Delete all events for technician stream. Returns deleted count."""
        ...


@runtime_checkable
class TechnicianWarehouseWipeDraftCleanup(Protocol):
    @beartype
    def has_draft_for_technician(self, technician_id: TechnicianId) -> bool: ...

    @beartype
    def delete_for_technician(self, technician_id: TechnicianId) -> int:
        """Delete active reconciliation drafts for technician. Returns deleted count."""
        ...


@runtime_checkable
class TechnicianWarehouseRepository(Protocol):
    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianWarehouse: ...

    @beartype
    def save(self, warehouse: TechnicianWarehouse, *, expected_version: int) -> None: ...

    @beartype
    def has_finalized_transfers_for_session(
        self,
        technician_id: TechnicianId,
        *,
        session_id: str,
    ) -> bool: ...


@beartype
def has_finalized_transfers_for_session_in_events(
    events: list[WarehouseEvent],
    *,
    session_id: str,
) -> bool:
    return any(
        isinstance(event, TechnicianWarehouseTransferFinalized) and event.session_id == session_id
        for event in events
    )


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseDelta:
    warehouse_inventory_id: str
    inventory_moment: datetime
    warehouse_delta_by_sku: dict[str, Decimal]
    calculated_stock_by_sku: dict[str, Decimal]
    actual_stock_by_sku: dict[str, Decimal]
    transfer_refs: tuple[ImportedTransferRef, ...]
    unmatched_products: tuple[UnmatchedMsProduct, ...]
    previous_actual_by_sku: dict[str, Decimal] = field(default_factory=dict)
    supply_in_by_sku: dict[str, Decimal] = field(default_factory=dict)
    returns_by_sku: dict[str, Decimal] = field(default_factory=dict)
    loadings_by_sku: dict[str, Decimal] = field(default_factory=dict)


@runtime_checkable
class TechnicianWarehouseDeltaPort(Protocol):
    async def get_delta(
        self,
        technician_id: TechnicianId,
        *,
        after: datetime | None,
        until: datetime,
        skip_import: bool = False,
    ) -> TechnicianWarehouseDelta | None: ...


@runtime_checkable
class TechnicianWarehouseCommandExecutor(Protocol):
    @beartype
    def execute(
        self,
        technician_id: TechnicianId,
        command: Callable[[TechnicianWarehouse], T],
    ) -> T: ...


@runtime_checkable
class DomainEventPublisher(Protocol):
    @beartype
    def publish(self, event: DomainEvent) -> None: ...


@runtime_checkable
class SeedProductCatalog(Protocol):
    @beartype
    def code_to_name(self) -> Mapping[str, str]:
        """All product catalog codes → display name (template / completeness check)."""
        ...


@beartype
@dataclass(frozen=True, slots=True)
class LoadingSubmittedRef:
    event_id: str
    technician_id: TechnicianId
    machine_id: MachineId
    submitted_at: datetime


@runtime_checkable
class WarehouseLoadingBackfillSource(Protocol):
    @beartype
    def list_loading_submitted(
        self,
        *,
        technician_id: TechnicianId | None,
    ) -> tuple[LoadingSubmittedRef, ...]:
        """LoadingSubmitted refs ordered by submitted_at ascending. None = all techs."""
        ...

    @beartype
    def list_observed_source_event_ids(
        self,
        *,
        technician_id: TechnicianId | None,
    ) -> frozenset[str]:
        """source_event_id already present as TechnicianWarehouseLoadingObserved."""
        ...
