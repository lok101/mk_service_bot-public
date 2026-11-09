from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.inventory_reconciliation.import_sales import ImportKitVendingSalesResult
from src.application.inventory_reconciliation.ports import (
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.inventory_reconciliation.refresh_targets import (
    compute_machines_to_refresh,
)
from src.domain.ids import MachineId


@runtime_checkable
class ImportSalesExecutor(Protocol):
    @beartype
    def execute(
        self,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> ImportKitVendingSalesResult: ...


@runtime_checkable
class RefreshPendingExecutor(Protocol):
    @beartype
    def execute(self, *, machine_id: MachineId | None = None) -> object: ...


@beartype
@dataclass(frozen=True, slots=True)
class BackfillMissingSalesFromKitResult:
    window_from: datetime
    window_to: datetime
    inserted: int = 0
    skipped_unmapped: int = 0
    skipped_unresolved_product: int = 0
    skipped_no_machine_code: int = 0
    holding_skip_count: int = 0
    refreshed_machine_count: int = 0


@beartype
@dataclass(frozen=True, slots=True)
class BackfillMissingSalesFromKit:
    import_sales: ImportSalesExecutor
    sales_store: MachineSalesStore
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    refresh_pending: RefreshPendingExecutor
    tolerance_seconds: int

    @beartype
    def execute(
        self,
        *,
        since: datetime,
        until: datetime,
        refresh_settlement: bool = False,
    ) -> BackfillMissingSalesFromKitResult:
        result = self.import_sales.execute(since=since, until=until)
        if not refresh_settlement:
            return BackfillMissingSalesFromKitResult(
                window_from=since,
                window_to=until,
                inserted=result.inserted,
                skipped_unmapped=result.skipped_unmapped,
                skipped_unresolved_product=result.skipped_unresolved_product,
                skipped_no_machine_code=result.skipped_no_machine_code,
                holding_skip_count=result.holding_skip_count,
                refreshed_machine_count=0,
            )
        cursor = self.sales_store.load_global_cursor()
        machines = compute_machines_to_refresh(
            affected_machine_ids=result.affected_machine_ids,
            reconciliation_repo=self.reconciliation_repo,
            cursor=cursor,
            tolerance_seconds=self.tolerance_seconds,
        )
        for machine_id in machines:
            self.refresh_pending.execute(machine_id=machine_id)
        return BackfillMissingSalesFromKitResult(
            window_from=since,
            window_to=until,
            inserted=result.inserted,
            skipped_unmapped=result.skipped_unmapped,
            skipped_unresolved_product=result.skipped_unresolved_product,
            skipped_no_machine_code=result.skipped_no_machine_code,
            holding_skip_count=result.holding_skip_count,
            refreshed_machine_count=len(machines),
        )
