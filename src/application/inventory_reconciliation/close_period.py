from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation.party_names import resolve_frozen_party_names
from src.application.inventory_reconciliation.period_snapshot_builder import PeriodSnapshotBuilder
from src.application.inventory_reconciliation.ports import (
    MachineRevisionHistoryReader,
    MachineSalesStore,
    PeriodPartyNamesLookup,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_operations.events import RevisionCompleted


@beartype
def build_period_snapshot(
    *,
    opening: RevisionCompleted,
    closing: RevisionCompleted,
    form_submission_store: FormSubmissionStore,
    revision_history: MachineRevisionHistoryReader,
    sales_store: MachineSalesStore,
    coffee_recipe_repo: CoffeeRecipeRepository,
    domain_product_store: DomainProductStore,
    tolerance_seconds: int,
    location_name: str,
    technician_name: str,
) -> ResponsibilityPeriodReconciliation:
    builder = PeriodSnapshotBuilder(
        form_submission_store=form_submission_store,
        revision_history=revision_history,
        sales_store=sales_store,
        coffee_recipe_repo=coffee_recipe_repo,
        domain_product_store=domain_product_store,
        tolerance_seconds=tolerance_seconds,
    )
    return builder.build_from_revision_pair(
        opening,
        closing,
        location_name=location_name,
        technician_name=technician_name,
    )


@beartype
@dataclass(frozen=True, slots=True)
class CloseResponsibilityPeriodOnRevision:
    form_submission_store: FormSubmissionStore
    revision_history: MachineRevisionHistoryReader
    sales_store: MachineSalesStore
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    coffee_recipe_repo: CoffeeRecipeRepository
    domain_product_store: DomainProductStore
    tolerance_seconds: int
    party_names_lookup: PeriodPartyNamesLookup

    @beartype
    def execute(
        self,
        *,
        closing_event: RevisionCompleted,
    ) -> ResponsibilityPeriodReconciliation | None:
        revisions = self.revision_history.list_revisions(closing_event.machine_id)
        closing_index = next(
            (
                index
                for index, revision in enumerate(revisions)
                if revision.revision_id == closing_event.revision_id
            ),
            None,
        )
        if closing_index is None or closing_index == 0:
            return None

        opening = revisions[closing_index - 1]
        period_id = f"{opening.revision_id.value}:{closing_event.revision_id.value}"
        existing = self.reconciliation_repo.get_by_period_id(period_id)
        if existing is not None and (existing.ledger_posted or existing.reconciled):
            return None

        location_name, technician_name = resolve_frozen_party_names(
            self.party_names_lookup,
            machine_id=closing_event.machine_id,
            technician_id=opening.technician_id,
            period_id=period_id,
            existing=existing,
        )
        snapshot = build_period_snapshot(
            opening=opening,
            closing=closing_event,
            form_submission_store=self.form_submission_store,
            revision_history=self.revision_history,
            sales_store=self.sales_store,
            coffee_recipe_repo=self.coffee_recipe_repo,
            domain_product_store=self.domain_product_store,
            tolerance_seconds=self.tolerance_seconds,
            location_name=location_name,
            technician_name=technician_name,
        )
        self.reconciliation_repo.save(snapshot)
        return snapshot
