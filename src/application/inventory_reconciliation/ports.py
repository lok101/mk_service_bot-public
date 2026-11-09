from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.kitvending import (
    KitSalePriceRow,
    KitSaleResolveSkip,
    KitSaleResolveSuccess,
    KitVendingFetchStats,
    KitVendingSaleRow,
    RawKitSaleIdentity,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.coverage import ReconciliationStatus
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_operations.events import LoadingSubmitted, RevisionCompleted
from src.domain.machine_sales import MachineSale


@runtime_checkable
class VendingMachineCodeResolver(Protocol):
    @beartype
    def resolve(self, vending_machine_code: str) -> MachineId | None: ...

    @beartype
    def list_codes(self) -> tuple[str, ...]: ...


@runtime_checkable
class PeriodPartyNamesLookup(Protocol):
    @beartype
    def location_name(self, machine_id: MachineId) -> str | None: ...

    @beartype
    def technician_name(self, technician_id: TechnicianId) -> str | None: ...


@runtime_checkable
class KitVendingClient(Protocol):
    @beartype
    def fetch_all(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> list[KitVendingSaleRow]: ...

    @property
    def last_fetch_stats(self) -> KitVendingFetchStats: ...


@runtime_checkable
class KitSalesWindowPriceFetcher(Protocol):
    @beartype
    def fetch_price_rows(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
    ) -> Sequence[KitSalePriceRow]: ...


@runtime_checkable
class KitPortionSalesGateway(Protocol):
    @beartype
    def fetch_raw_window(
        self,
        *,
        from_date: datetime,
        to_date: datetime,
    ) -> list[RawKitSaleIdentity]: ...

    @beartype
    def resolve(self, source_id: str) -> KitSaleResolveSuccess | KitSaleResolveSkip: ...


@runtime_checkable
class MachineSalesStore(Protocol):
    @beartype
    def insert_if_absent(self, sale: MachineSale) -> bool: ...

    @beartype
    def set_resolve_status(self, source_id: str, resolve_status: str) -> None: ...

    @beartype
    def find_in_window(
        self,
        machine_id: MachineId,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]: ...

    @beartype
    def find_in_global_window(
        self,
        *,
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]: ...

    @beartype
    def list_source_ids(
        self,
        *,
        machine_id: MachineId,
        opened_at: datetime,
        closed_at: datetime,
    ) -> frozenset[str]: ...

    @beartype
    def find_after_by_machine_code(
        self,
        machine_code: str,
        *,
        after: datetime,
    ) -> tuple[MachineSale, ...]: ...

    @beartype
    def last_occurred_at(self, machine_id: MachineId) -> datetime | None: ...

    @beartype
    def max_occurred_at(self) -> datetime | None: ...

    @beartype
    def load_global_cursor(self) -> datetime | None: ...

    @beartype
    def save_global_cursor(self, watermark: datetime) -> None: ...

    @beartype
    def set_price_if_absent(self, source_id: str, price: Decimal) -> bool: ...

    @beartype
    def patch_company_id_if_missing(self, source_id: str, company_id: int) -> bool: ...

    @beartype
    def list_with_missing_company_id(self) -> tuple[MachineSale, ...]: ...

    @beartype
    def list_machine_ids_with_sales(self) -> tuple[MachineId, ...]: ...

    @beartype
    def list_with_company_id(self, machine_id: MachineId) -> tuple[MachineSale, ...]: ...

    @beartype
    def min_occurred_at_missing_price(self) -> datetime | None: ...

    @beartype
    def find_missing_price_before(self, before: datetime) -> tuple[MachineSale, ...]: ...


@runtime_checkable
class ResponsibilityPeriodReconciliationRepository(Protocol):
    @beartype
    def save(self, snapshot: ResponsibilityPeriodReconciliation) -> None: ...

    @beartype
    def get_by_period_id(
        self,
        period_id: str,
    ) -> ResponsibilityPeriodReconciliation | None: ...

    @beartype
    def get_by_opening_revision(
        self,
        machine_id: MachineId,
        opening_revision_id: RevisionId,
    ) -> ResponsibilityPeriodReconciliation | None: ...

    @beartype
    def list_complete_unposted(
        self,
        *,
        technician_id: TechnicianId | None = None,
    ) -> list[ResponsibilityPeriodReconciliation]: ...

    @beartype
    def list_by_status(
        self,
        *,
        status: ReconciliationStatus,
        machine_id: MachineId | None = None,
    ) -> list[ResponsibilityPeriodReconciliation]: ...

    @beartype
    def list_posted_unreconciled(
        self,
        *,
        technician_id: TechnicianId,
    ) -> list[ResponsibilityPeriodReconciliation]: ...

    @beartype
    def list_unreconciled_technician_ids(self) -> tuple[TechnicianId, ...]: ...

    @beartype
    def list_reconciliation_preview_technician_ids(self) -> tuple[TechnicianId, ...]: ...

    @beartype
    def mark_ledger_posted(self, period_id: str) -> None: ...

    @beartype
    def mark_reconciled(self, period_ids: tuple[str, ...]) -> None: ...

    @beartype
    def count_ledger_posted(self) -> int: ...

    @beartype
    def count_all(self) -> int: ...

    @beartype
    def delete_all(self) -> int: ...


@runtime_checkable
class MachineRevisionHistoryReader(Protocol):
    @beartype
    def list_revisions(self, machine_id: MachineId) -> tuple[RevisionCompleted, ...]: ...

    @beartype
    def list_loadings(self, machine_id: MachineId) -> tuple[LoadingSubmitted, ...]: ...
