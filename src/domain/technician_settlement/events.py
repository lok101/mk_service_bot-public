from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from beartype import beartype

from src.domain.ids import (
    AccountabilityId,
    EventId,
    MachineId,
    ReconciliationSessionId,
    TechnicianId,
)

ReconciliationMode = Literal["inventory_delta", "exit_warehouse_closed"]
WarehouseSource = Literal["domain_technician_warehouse"]


@beartype
@dataclass(frozen=True, slots=True)
class WarehouseTransferRef:
    external_document_id: str
    content_hash: str


@beartype
@dataclass(frozen=True, slots=True)
class PeriodAccountabilityRecorded:
    event_id: EventId
    accountability_id: AccountabilityId
    technician_id: TechnicianId
    period_id: str
    machine_id: MachineId
    delta_by_sku: dict[str, Decimal]
    closed_at: datetime
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianReconciliationSessionCompleted:
    event_id: EventId
    session_id: ReconciliationSessionId
    technician_id: TechnicianId
    mode: ReconciliationMode
    anchor_at: datetime
    period_ids: tuple[str, ...]
    deferred_period_ids: tuple[str, ...]
    warehouse_inventory_id: str | None
    warehouse_inventory_moment: datetime | None
    warehouse_delta_by_sku: dict[str, Decimal]
    warehouse_source: WarehouseSource
    warehouse_transfer_refs: tuple[WarehouseTransferRef, ...]
    ledger_balance_before: dict[str, Decimal]
    residual_by_sku: dict[str, Decimal]
    finalized_at: datetime
    occurred_at: datetime
    executed_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianLedgerClearedByReconciliation:
    event_id: EventId
    session_id: ReconciliationSessionId
    technician_id: TechnicianId
    period_ids: tuple[str, ...]
    cleared_by_sku: dict[str, Decimal]
    residual_by_sku: dict[str, Decimal]
    occurred_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class TechnicianReconciliationSessionCommitted:
    event_id: EventId
    session_id: ReconciliationSessionId
    technician_id: TechnicianId
    mode: ReconciliationMode
    anchor_at: datetime
    period_ids: tuple[str, ...]
    deferred_period_ids: tuple[str, ...]
    warehouse_inventory_id: str | None
    warehouse_inventory_moment: datetime | None
    warehouse_delta_by_sku: dict[str, Decimal]
    warehouse_source: WarehouseSource
    warehouse_transfer_refs: tuple[WarehouseTransferRef, ...]
    ledger_balance_before: dict[str, Decimal]
    cleared_by_sku: dict[str, Decimal]
    residual_by_sku: dict[str, Decimal]
    finalized_at: datetime
    executed_at: datetime
    occurred_at: datetime


SettlementEvent = (
    PeriodAccountabilityRecorded
    | TechnicianReconciliationSessionCompleted
    | TechnicianLedgerClearedByReconciliation
    | TechnicianReconciliationSessionCommitted
)
