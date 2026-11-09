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
class RefreshPendingResult:
    transitioned_to_complete: tuple[ResponsibilityPeriodReconciliation, ...]


@beartype
@dataclass(frozen=True, slots=True)
class RefreshPendingPeriodReconciliations:
    repo: ResponsibilityPeriodReconciliationRepository
    sales_store: MachineSalesStore
    coffee_recipe_repo: CoffeeRecipeRepository
    domain_product_store: DomainProductStore
    form_submission_store: FormSubmissionStore
    revision_history: MachineRevisionHistoryReader
    tolerance_seconds: int

    @beartype
    def execute(self, *, machine_id: MachineId | None = None) -> RefreshPendingResult:
        transitioned: list[ResponsibilityPeriodReconciliation] = []
        for snapshot in self.repo.list_by_status(
            status="pending_sales",
            machine_id=machine_id,
        ):
            if snapshot.reconciled or snapshot.ledger_posted:
                continue
            old_status = snapshot.status
            updated = recalculate_snapshot(
                snapshot,
                sales_store=self.sales_store,
                coffee_recipe_repo=self.coffee_recipe_repo,
                domain_product_store=self.domain_product_store,
                form_submission_store=self.form_submission_store,
                revision_history=self.revision_history,
                tolerance_seconds=self.tolerance_seconds,
            )
            self.repo.save(updated)
            if old_status == "pending_sales" and updated.status == "complete":
                transitioned.append(updated)
        return RefreshPendingResult(transitioned_to_complete=tuple(transitioned))
