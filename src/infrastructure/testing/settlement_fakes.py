from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal

from beartype import beartype

from src.application.inventory_reconciliation import PeriodReconciliationNotFound
from src.application.inventory_reconciliation.ports import (
    MachineRevisionHistoryReader,
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.technician_settlement import TechnicianSettlementConcurrencyError
from src.application.technician_settlement.ports import (
    TechnicianSettlementEventStore,
    TechnicianSettlementRepository,
)
from src.application.technician_warehouse.ports import TechnicianWarehouseDelta
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.coverage import ReconciliationStatus
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_operations.events import LoadingSubmitted, RevisionCompleted
from src.domain.machine_sales import MachineSale
from src.domain.technician_settlement import TechnicianSettlement
from src.domain.technician_settlement.events import SettlementEvent
from src.infrastructure.mongodb.errors import EventStoreConcurrencyError


@beartype
@dataclass(slots=True)
class InMemoryMachineRevisionHistoryReader(MachineRevisionHistoryReader):
    _revisions: list[RevisionCompleted] = field(default_factory=list)
    _loadings: list[LoadingSubmitted] = field(default_factory=list)

    @beartype
    def add_revision(self, revision: RevisionCompleted) -> None:
        self._revisions.append(revision)

    @beartype
    def add_loading(self, loading: LoadingSubmitted) -> None:
        self._loadings.append(loading)

    @beartype
    def list_revisions(self, machine_id: MachineId) -> tuple[RevisionCompleted, ...]:
        revisions = [revision for revision in self._revisions if revision.machine_id == machine_id]
        return tuple(sorted(revisions, key=lambda revision: revision.completed_at))

    @beartype
    def list_loadings(self, machine_id: MachineId) -> tuple[LoadingSubmitted, ...]:
        loadings = [loading for loading in self._loadings if loading.machine_id == machine_id]
        return tuple(sorted(loadings, key=lambda loading: loading.occurred_at))


@beartype
@dataclass(slots=True)
class InMemoryMachineSalesStore(MachineSalesStore):
    _by_source_id: dict[str, MachineSale] = field(default_factory=dict)
    _poll_cursor: datetime | None = field(default=None, repr=False)

    @beartype
    def insert_if_absent(self, sale: MachineSale) -> bool:
        if sale.source_id in self._by_source_id:
            return False
        self._by_source_id[sale.source_id] = sale
        return True

    @beartype
    def set_resolve_status(self, source_id: str, resolve_status: str) -> None:
        existing = self._by_source_id.get(source_id)
        if existing is None:
            raise KeyError(f"machine sale not found: {source_id}")
        self._by_source_id[source_id] = replace(existing, resolve_status=resolve_status)

    @beartype
    def find_in_window(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]:
        return tuple(
            sale
            for sale in self._by_source_id.values()
            if sale.machine_id == machine_id and opened_at < sale.occurred_at <= closed_at
        )

    @beartype
    def find_in_global_window(
        self,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]:
        return tuple(
            sorted(
                (
                    sale
                    for sale in self._by_source_id.values()
                    if opened_at <= sale.occurred_at < closed_at
                ),
                key=lambda sale: sale.occurred_at,
            ),
        )

    @beartype
    def list_source_ids(
        self,
        *,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
    ) -> frozenset[str]:
        return frozenset(
            sale.source_id
            for sale in self.find_in_window(
                machine_id,
                opened_at=opened_at,
                closed_at=closed_at,
            )
        )

    @beartype
    def find_after_by_machine_code(
        self,
        machine_code: str,
        *,
        after: datetime,
    ) -> tuple[MachineSale, ...]:
        return tuple(
            sorted(
                (
                    sale
                    for sale in self._by_source_id.values()
                    if sale.machine_code == machine_code and sale.occurred_at > after
                ),
                key=lambda sale: sale.occurred_at,
            ),
        )

    @beartype
    def last_occurred_at(self, machine_id: MachineId) -> datetime | None:
        times = [
            sale.occurred_at
            for sale in self._by_source_id.values()
            if sale.machine_id == machine_id
        ]
        return max(times) if times else None

    @beartype
    def max_occurred_at(self) -> datetime | None:
        times = [sale.occurred_at for sale in self._by_source_id.values()]
        return max(times) if times else None

    @beartype
    def load_global_cursor(self) -> datetime | None:
        sales_max = self.max_occurred_at()
        if self._poll_cursor is None:
            return sales_max
        if sales_max is None:
            return self._poll_cursor
        return max(self._poll_cursor, sales_max)

    @beartype
    def save_global_cursor(self, watermark: datetime) -> None:
        self._poll_cursor = watermark

    @beartype
    def set_price_if_absent(self, source_id: str, price: Decimal) -> bool:
        existing = self._by_source_id.get(source_id)
        if existing is None or existing.price is not None:
            return False
        self._by_source_id[source_id] = replace(existing, price=price)
        return True

    @beartype
    def patch_company_id_if_missing(self, source_id: str, company_id: int) -> bool:
        existing = self._by_source_id.get(source_id)
        if existing is None or existing.company_id is not None:
            return False
        self._by_source_id[source_id] = replace(existing, company_id=company_id)
        return True

    @beartype
    def list_with_missing_company_id(self) -> tuple[MachineSale, ...]:
        return tuple(
            sorted(
                (sale for sale in self._by_source_id.values() if sale.company_id is None),
                key=lambda sale: (sale.occurred_at, sale.source_id),
            ),
        )

    @beartype
    def list_machine_ids_with_sales(self) -> tuple[MachineId, ...]:
        machine_ids = {sale.machine_id for sale in self._by_source_id.values()}
        return tuple(sorted(machine_ids, key=lambda item: item.value))

    @beartype
    def list_with_company_id(self, machine_id: MachineId) -> tuple[MachineSale, ...]:
        return tuple(
            sorted(
                (
                    sale
                    for sale in self._by_source_id.values()
                    if sale.machine_id == machine_id and sale.company_id is not None
                ),
                key=lambda sale: (sale.occurred_at, sale.source_id),
            ),
        )

    @beartype
    def min_occurred_at_missing_price(self) -> datetime | None:
        times = [sale.occurred_at for sale in self._by_source_id.values() if sale.price is None]
        return min(times) if times else None

    @beartype
    def find_missing_price_before(self, before: datetime) -> tuple[MachineSale, ...]:
        return tuple(
            sorted(
                (
                    sale
                    for sale in self._by_source_id.values()
                    if sale.price is None and sale.occurred_at < before
                ),
                key=lambda sale: sale.occurred_at,
            ),
        )


@beartype
@dataclass(slots=True)
class InMemoryPeriodReconciliationRepository(ResponsibilityPeriodReconciliationRepository):
    _by_period_id: dict[str, ResponsibilityPeriodReconciliation] = field(default_factory=dict)
    ledger_posted_periods: list[str] = field(default_factory=list)
    reconciled_periods: list[tuple[str, ...]] = field(default_factory=list)

    @beartype
    def save(self, snapshot: ResponsibilityPeriodReconciliation) -> None:
        self._by_period_id[snapshot.period_id] = snapshot

    @beartype
    def get_by_period_id(self, period_id: str) -> ResponsibilityPeriodReconciliation | None:
        return self._by_period_id.get(period_id)

    @beartype
    def get_by_opening_revision(
        self,
        machine_id: MachineId,
        opening_revision_id: RevisionId,
    ) -> ResponsibilityPeriodReconciliation | None:
        for snapshot in self._by_period_id.values():
            if (
                snapshot.machine_id == machine_id
                and snapshot.opening_revision_id == opening_revision_id
            ):
                return snapshot
        return None

    @beartype
    def list_complete_unposted(
        self,
        *,
        technician_id: TechnicianId | None = None,
    ) -> list[ResponsibilityPeriodReconciliation]:
        return [
            snapshot
            for snapshot in self._by_period_id.values()
            if snapshot.status == "complete"
            and not snapshot.ledger_posted
            and (technician_id is None or snapshot.responsible_technician_id == technician_id)
        ]

    @beartype
    def list_posted_unreconciled(
        self,
        *,
        technician_id: TechnicianId,
    ) -> list[ResponsibilityPeriodReconciliation]:
        return [
            snapshot
            for snapshot in self._by_period_id.values()
            if snapshot.status == "complete"
            and snapshot.ledger_posted
            and not snapshot.reconciled
            and snapshot.responsible_technician_id == technician_id
        ]

    @beartype
    def list_unreconciled_technician_ids(self) -> tuple[TechnicianId, ...]:
        technician_ids = {
            snapshot.responsible_technician_id.value
            for snapshot in self._by_period_id.values()
            if snapshot.status == "complete" and snapshot.ledger_posted and not snapshot.reconciled
        }
        return tuple(TechnicianId(technician_id) for technician_id in sorted(technician_ids))

    @beartype
    def list_reconciliation_preview_technician_ids(self) -> tuple[TechnicianId, ...]:
        posted_ids = {
            snapshot.responsible_technician_id.value
            for snapshot in self._by_period_id.values()
            if snapshot.status == "complete" and snapshot.ledger_posted and not snapshot.reconciled
        }
        pending_ids = {
            snapshot.responsible_technician_id.value
            for snapshot in self._by_period_id.values()
            if snapshot.status == "pending_sales"
        }
        union = sorted(posted_ids | pending_ids)
        return tuple(TechnicianId(technician_id) for technician_id in union)

    @beartype
    def list_by_status(
        self,
        *,
        status: ReconciliationStatus,
        machine_id: MachineId | None = None,
    ) -> list[ResponsibilityPeriodReconciliation]:
        return [
            snapshot
            for snapshot in self._by_period_id.values()
            if snapshot.status == status
            and (machine_id is None or snapshot.machine_id == machine_id)
        ]

    @beartype
    def mark_ledger_posted(self, period_id: str) -> None:
        if self.get_by_period_id(period_id) is None:
            raise PeriodReconciliationNotFound(period_id=period_id)
        self.ledger_posted_periods.append(period_id)
        old = self._by_period_id[period_id]
        self._by_period_id[period_id] = replace(old, ledger_posted=True)

    @beartype
    def mark_reconciled(self, period_ids: tuple[str, ...]) -> None:
        if not period_ids:
            return
        for period_id in period_ids:
            if self.get_by_period_id(period_id) is None:
                raise PeriodReconciliationNotFound(period_id=period_id)
        self.reconciled_periods.append(period_ids)
        for period_id in period_ids:
            old = self._by_period_id[period_id]
            self._by_period_id[period_id] = replace(old, reconciled=True)

    @beartype
    def count_ledger_posted(self) -> int:
        return sum(1 for snapshot in self._by_period_id.values() if snapshot.ledger_posted)

    @beartype
    def count_all(self) -> int:
        return len(self._by_period_id)

    @beartype
    def delete_all(self) -> int:
        count = len(self._by_period_id)
        self._by_period_id.clear()
        return count


@beartype
@dataclass(slots=True)
class InMemoryTechnicianSettlementEventStore(TechnicianSettlementEventStore):
    _events: list[SettlementEvent] = field(default_factory=list)
    _aggregate_versions: dict[str, int] = field(default_factory=dict)

    @property
    def events(self) -> list[SettlementEvent]:
        return list(self._events)

    @beartype
    def append(self, event: SettlementEvent, *, expected_version: int) -> None:
        if expected_version < 0:
            raise ValueError("expected_version must be non-negative")
        if any(existing.event_id == event.event_id for existing in self._events):
            return
        aggregate_id = event.technician_id.value
        current_version = self._aggregate_versions.get(aggregate_id, 0)
        if expected_version != current_version:
            raise EventStoreConcurrencyError(
                f"Expected version {expected_version} for aggregate {aggregate_id!r}, "
                f"current is {current_version}",
            )
        self._events.append(event)
        self._aggregate_versions[aggregate_id] = expected_version + 1

    @beartype
    def get_events_for_technician(
        self,
        technician_id: TechnicianId,
    ) -> list[SettlementEvent]:
        return [event for event in self._events if event.technician_id == technician_id]

    @beartype
    def count_all(self) -> int:
        return len(self._events)

    @beartype
    def delete_all(self) -> int:
        count = len(self._events)
        self._events.clear()
        self._aggregate_versions.clear()
        return count


@beartype
@dataclass(frozen=True, slots=True)
class InMemoryTechnicianSettlementRepository(TechnicianSettlementRepository):
    event_store: InMemoryTechnicianSettlementEventStore

    @property
    def events(self) -> list[SettlementEvent]:
        return self.event_store.events

    @beartype
    def get(self, technician_id: TechnicianId) -> TechnicianSettlement:
        events = self.event_store.get_events_for_technician(technician_id)
        return TechnicianSettlement.rehydrate(
            technician_id,
            events,
            loaded_version=len(events),
        )

    @beartype
    def save(self, aggregate: TechnicianSettlement) -> None:
        pending = aggregate.collect_events()
        if len(pending) > 1:
            raise ValueError("one event per save boundary")
        if not pending:
            return
        try:
            self.event_store.append(
                pending[0],
                expected_version=aggregate.loaded_version,
            )
        except EventStoreConcurrencyError as error:
            raise TechnicianSettlementConcurrencyError(
                technician_id=aggregate.technician_id,
            ) from error


@beartype
@dataclass(slots=True)
class RecordingPostAccountability:
    snapshots: list[ResponsibilityPeriodReconciliation] = field(default_factory=list)

    @beartype
    def execute(self, *, snapshot: ResponsibilityPeriodReconciliation) -> None:
        self.snapshots.append(snapshot)


@beartype
@dataclass(slots=True)
class FakeTechnicianWarehouseDeltaPort:
    delta: TechnicianWarehouseDelta | None = None

    async def get_delta(
        self,
        technician_id: TechnicianId,
        *,
        after: datetime | None,
        until: datetime,
        skip_import: bool = False,
    ) -> TechnicianWarehouseDelta | None:
        _ = technician_id, after, until, skip_import
        return self.delta
