from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from beartype import beartype

from src.domain.ids import (
    AccountabilityId,
    EventId,
    MachineId,
    ReconciliationSessionId,
    TechnicianId,
)
from src.domain.technician_settlement.events import (
    PeriodAccountabilityRecorded,
    ReconciliationMode,
    SettlementEvent,
    TechnicianLedgerClearedByReconciliation,
    TechnicianReconciliationSessionCommitted,
    TechnicianReconciliationSessionCompleted,
    WarehouseSource,
    WarehouseTransferRef,
)


@beartype
@dataclass(frozen=True, slots=True)
class RecordPeriodAccountability:
    accountability_id: AccountabilityId
    period_id: str
    machine_id: MachineId
    delta_by_sku: dict[str, Decimal]
    closed_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class CompleteReconciliationSession:
    session_id: ReconciliationSessionId
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
    executed_at: datetime


@beartype
@dataclass(frozen=True, slots=True)
class SessionCompletionResult:
    committed_event: TechnicianReconciliationSessionCommitted
    session_id: ReconciliationSessionId
    mode: ReconciliationMode
    period_ids: tuple[str, ...]
    deferred_period_ids: tuple[str, ...]
    warehouse_inventory_id: str | None
    warehouse_source: WarehouseSource
    residual_by_sku: dict[str, Decimal]
    cleared_by_sku: dict[str, Decimal]

    @classmethod
    @beartype
    def from_committed(
        cls,
        committed: TechnicianReconciliationSessionCommitted,
    ) -> SessionCompletionResult:
        return cls(
            committed_event=committed,
            session_id=committed.session_id,
            mode=committed.mode,
            period_ids=committed.period_ids,
            deferred_period_ids=committed.deferred_period_ids,
            warehouse_inventory_id=committed.warehouse_inventory_id,
            warehouse_source=committed.warehouse_source,
            residual_by_sku=dict(committed.residual_by_sku),
            cleared_by_sku=dict(committed.cleared_by_sku),
        )


@beartype
def _committed_from_legacy_pair(
    completed: TechnicianReconciliationSessionCompleted,
    cleared: TechnicianLedgerClearedByReconciliation,
) -> TechnicianReconciliationSessionCommitted:
    return TechnicianReconciliationSessionCommitted(
        event_id=completed.event_id,
        session_id=completed.session_id,
        technician_id=completed.technician_id,
        mode=completed.mode,
        anchor_at=completed.anchor_at,
        period_ids=completed.period_ids,
        deferred_period_ids=completed.deferred_period_ids,
        warehouse_inventory_id=completed.warehouse_inventory_id,
        warehouse_inventory_moment=completed.warehouse_inventory_moment,
        warehouse_delta_by_sku=dict(completed.warehouse_delta_by_sku),
        warehouse_source=completed.warehouse_source,
        warehouse_transfer_refs=completed.warehouse_transfer_refs,
        ledger_balance_before=dict(completed.ledger_balance_before),
        cleared_by_sku=dict(cleared.cleared_by_sku),
        residual_by_sku=dict(cleared.residual_by_sku),
        finalized_at=completed.finalized_at,
        executed_at=completed.executed_at,
        occurred_at=completed.occurred_at,
    )


@beartype
@dataclass(slots=True)
class TechnicianSettlement:
    technician_id: TechnicianId
    _balance_by_sku: dict[str, Decimal] = field(default_factory=dict, repr=False)
    _recorded_accountability_ids: set[str] = field(default_factory=set, repr=False)
    _recorded_by_accountability_id: dict[str, PeriodAccountabilityRecorded] = field(
        default_factory=dict,
        repr=False,
    )
    _committed_session_ids: set[str] = field(default_factory=set, repr=False)
    _session_results: dict[str, SessionCompletionResult] = field(
        default_factory=dict,
        repr=False,
    )
    _pending_legacy_completed: dict[str, TechnicianReconciliationSessionCompleted] = field(
        default_factory=dict,
        repr=False,
    )
    _last_session_finalized_at: datetime | None = field(default=None, repr=False)
    _pending_events: list[SettlementEvent] = field(default_factory=list, repr=False)
    _loaded_version: int = field(default=0, repr=False)

    @property
    @beartype
    def loaded_version(self) -> int:
        return self._loaded_version

    @classmethod
    @beartype
    def empty(cls, technician_id: TechnicianId) -> TechnicianSettlement:
        return cls(technician_id=technician_id)

    @classmethod
    @beartype
    def rehydrate(
        cls,
        technician_id: TechnicianId,
        events: list[SettlementEvent],
        *,
        loaded_version: int | None = None,
    ) -> TechnicianSettlement:
        aggregate = cls.empty(technician_id)
        for event in events:
            aggregate._apply(event)
        aggregate._pending_events.clear()
        aggregate._loaded_version = len(events) if loaded_version is None else loaded_version
        return aggregate

    @beartype
    def record_period_accountability(
        self,
        command: RecordPeriodAccountability,
    ) -> PeriodAccountabilityRecorded | None:
        if command.accountability_id.value in self._recorded_accountability_ids:
            return self._recorded_by_accountability_id[command.accountability_id.value]
        occurred_at = datetime.now(tz=UTC)
        event = PeriodAccountabilityRecorded(
            event_id=EventId(f"event-{uuid.uuid4()}"),
            accountability_id=command.accountability_id,
            technician_id=self.technician_id,
            period_id=command.period_id,
            machine_id=command.machine_id,
            delta_by_sku=dict(command.delta_by_sku),
            closed_at=command.closed_at,
            occurred_at=occurred_at,
        )
        self._record(event)
        return event

    @beartype
    def complete_reconciliation_session(
        self,
        command: CompleteReconciliationSession,
    ) -> SessionCompletionResult:
        if command.session_id.value in self._committed_session_ids:
            return self._session_results[command.session_id.value]
        occurred_at = datetime.now(tz=UTC)
        cleared_by_sku = dict(command.ledger_balance_before)
        committed = TechnicianReconciliationSessionCommitted(
            event_id=EventId(f"event-{uuid.uuid4()}"),
            session_id=command.session_id,
            technician_id=self.technician_id,
            mode=command.mode,
            anchor_at=command.anchor_at,
            period_ids=command.period_ids,
            deferred_period_ids=command.deferred_period_ids,
            warehouse_inventory_id=command.warehouse_inventory_id,
            warehouse_inventory_moment=command.warehouse_inventory_moment,
            warehouse_delta_by_sku=dict(command.warehouse_delta_by_sku),
            warehouse_source=command.warehouse_source,
            warehouse_transfer_refs=command.warehouse_transfer_refs,
            ledger_balance_before=dict(command.ledger_balance_before),
            cleared_by_sku=cleared_by_sku,
            residual_by_sku=dict(command.residual_by_sku),
            finalized_at=command.finalized_at,
            executed_at=command.executed_at,
            occurred_at=occurred_at,
        )
        self._record(committed)
        return self._session_results[command.session_id.value]

    @beartype
    def net_balance_by_sku(self) -> dict[str, Decimal]:
        return dict(self._balance_by_sku)

    @beartype
    def last_session_finalized_at(self) -> datetime | None:
        return self._last_session_finalized_at

    @beartype
    def completion_result_for(
        self,
        session_id: ReconciliationSessionId,
    ) -> SessionCompletionResult | None:
        if session_id.value not in self._committed_session_ids:
            return None
        return self._session_results[session_id.value]

    @beartype
    def collect_events(self) -> list[SettlementEvent]:
        return list(self._pending_events)

    @beartype
    def clear_pending_events(self) -> None:
        self._pending_events.clear()

    @beartype
    def _record(self, event: SettlementEvent) -> None:
        self._apply(event)
        self._pending_events.append(event)

    @beartype
    def _apply(self, event: SettlementEvent) -> None:
        if isinstance(event, PeriodAccountabilityRecorded):
            self._apply_accountability(event)
            return
        if isinstance(event, TechnicianReconciliationSessionCommitted):
            self._apply_session_committed(event)
            return
        if isinstance(event, TechnicianLedgerClearedByReconciliation):
            self._apply_cleared(event)
            return
        if isinstance(event, TechnicianReconciliationSessionCompleted):
            self._apply_legacy_session_completed(event)

    @beartype
    def _apply_accountability(self, event: PeriodAccountabilityRecorded) -> None:
        self._recorded_accountability_ids.add(event.accountability_id.value)
        self._recorded_by_accountability_id[event.accountability_id.value] = event
        for product_code, delta in event.delta_by_sku.items():
            self._balance_by_sku[product_code] = (
                self._balance_by_sku.get(product_code, Decimal("0")) + delta
            )

    @beartype
    def _apply_session_committed(
        self,
        event: TechnicianReconciliationSessionCommitted,
    ) -> None:
        result = SessionCompletionResult.from_committed(event)
        self._committed_session_ids.add(event.session_id.value)
        self._session_results[event.session_id.value] = result
        self._pending_legacy_completed.pop(event.session_id.value, None)
        for product_code, cleared in event.cleared_by_sku.items():
            self._balance_by_sku[product_code] = (
                self._balance_by_sku.get(product_code, Decimal("0")) - cleared
            )
        self._touch_last_finalized_at(event.finalized_at)

    @beartype
    def _apply_cleared(self, event: TechnicianLedgerClearedByReconciliation) -> None:
        for product_code, cleared in event.cleared_by_sku.items():
            self._balance_by_sku[product_code] = (
                self._balance_by_sku.get(product_code, Decimal("0")) - cleared
            )
        completed = self._pending_legacy_completed.pop(event.session_id.value, None)
        if completed is None:
            return
        committed = _committed_from_legacy_pair(completed, event)
        result = SessionCompletionResult.from_committed(committed)
        self._committed_session_ids.add(event.session_id.value)
        self._session_results[event.session_id.value] = result
        self._touch_last_finalized_at(completed.finalized_at)

    @beartype
    def _apply_legacy_session_completed(
        self,
        event: TechnicianReconciliationSessionCompleted,
    ) -> None:
        self._pending_legacy_completed[event.session_id.value] = event

    @beartype
    def _touch_last_finalized_at(self, finalized_at: datetime) -> None:
        if (
            self._last_session_finalized_at is None
            or finalized_at > self._last_session_finalized_at
        ):
            self._last_session_finalized_at = finalized_at
