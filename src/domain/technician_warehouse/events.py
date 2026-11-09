from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.domain.ids import EventId, MachineId, TechnicianId
from src.domain.technician_warehouse.models import TechnicianWarehouseLine, TransferDirection


@runtime_checkable
class TechnicianWarehouseEvent(Protocol):
    @property
    def event_id(self) -> EventId: ...

    @property
    def technician_id(self) -> TechnicianId: ...

    @property
    def occurred_at(self) -> datetime: ...


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseTransferObserved:
    event_id: EventId
    technician_id: TechnicianId
    occurred_at: datetime
    external_document_id: str
    moment: datetime
    updated_at: datetime
    observed_at: datetime
    content_hash: str
    direction: TransferDirection
    lines: tuple[TechnicianWarehouseLine, ...]


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseTransferVoided:
    event_id: EventId
    technician_id: TechnicianId
    occurred_at: datetime
    external_document_id: str
    previous_content_hash: str
    observed_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseLoadingObserved:
    event_id: EventId
    technician_id: TechnicianId
    occurred_at: datetime
    source_event_id: str
    machine_id: MachineId
    submitted_at: datetime
    lines: tuple[TechnicianWarehouseLine, ...]


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseInventoryCounted:
    event_id: EventId
    technician_id: TechnicianId
    occurred_at: datetime
    inventory_id: str
    form_token: str
    counted_at: datetime
    lines: tuple[tuple[str, Decimal], ...]
    baseline: bool


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseTransferFinalized:
    event_id: EventId
    technician_id: TechnicianId
    occurred_at: datetime
    session_id: str
    external_document_ids: tuple[str, ...]
    finalized_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianWarehouseExitClosed:
    event_id: EventId
    technician_id: TechnicianId
    occurred_at: datetime
    closed_at: datetime
    return_external_document_id: str
    return_content_hash: str


WarehouseEvent = (
    TechnicianWarehouseTransferObserved
    | TechnicianWarehouseTransferVoided
    | TechnicianWarehouseLoadingObserved
    | TechnicianWarehouseInventoryCounted
    | TechnicianWarehouseTransferFinalized
    | TechnicianWarehouseExitClosed
)
