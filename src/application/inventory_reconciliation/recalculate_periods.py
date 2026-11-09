from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation.period_snapshot_recalculate import (
    recalculate_snapshot,
)
from src.application.inventory_reconciliation.ports import (
    MachineRevisionHistoryReader,
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.ids import MachineId
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


@beartype
@dataclass(frozen=True, slots=True)
class RecalculatePeriodSnapshots:
    repo: ResponsibilityPeriodReconciliationRepository
    sales_store: MachineSalesStore
    coffee_recipe_repo: CoffeeRecipeRepository
    domain_product_store: DomainProductStore
    form_submission_store: FormSubmissionStore
    revision_history: MachineRevisionHistoryReader
    tolerance_seconds: int

    @beartype
    def execute(
        self,
        *,
        dry_run: bool,
        machine_id: MachineId | None = None,
        period_id: str | None = None,
        all_complete: bool = False,
    ) -> tuple[str, ...]:
        snapshots = self._select(
            machine_id=machine_id,
            period_id=period_id,
            all_complete=all_complete,
        )
        if dry_run:
            return tuple(snapshot.period_id for snapshot in snapshots)
        for snapshot in snapshots:
            updated = recalculate_snapshot(
                snapshot,
                force=True,
                sales_store=self.sales_store,
                coffee_recipe_repo=self.coffee_recipe_repo,
                domain_product_store=self.domain_product_store,
                form_submission_store=self.form_submission_store,
                revision_history=self.revision_history,
                tolerance_seconds=self.tolerance_seconds,
            )
            self.repo.save(updated)
        return tuple(snapshot.period_id for snapshot in snapshots)

    @beartype
    def _select(
        self,
        *,
        machine_id: MachineId | None,
        period_id: str | None,
        all_complete: bool,
    ) -> list[ResponsibilityPeriodReconciliation]:
        if period_id is not None:
            snapshot = self.repo.get_by_period_id(period_id)
            if snapshot is None or snapshot.status != "complete":
                return []
            return [snapshot]
        if all_complete or machine_id is not None:
            return self.repo.list_by_status(status="complete", machine_id=machine_id)
        return []
