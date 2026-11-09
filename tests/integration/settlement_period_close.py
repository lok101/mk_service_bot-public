from __future__ import annotations

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation.close_period import (
    CloseResponsibilityPeriodOnRevision,
)
from src.application.inventory_reconciliation.ports import (
    MachineRevisionHistoryReader,
    MachineSalesStore,
    PeriodPartyNamesLookup,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.product_identity.ports import DomainProductStore


@beartype
def build_integration_close_responsibility_period(
    *,
    form_submission_store: FormSubmissionStore,
    revision_history: MachineRevisionHistoryReader,
    sales_store: MachineSalesStore,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    coffee_recipe_repo: CoffeeRecipeRepository,
    domain_product_store: DomainProductStore,
    party_names_lookup: PeriodPartyNamesLookup,
    tolerance_seconds: int = 0,
) -> CloseResponsibilityPeriodOnRevision:
    return CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_submission_store,
        revision_history=revision_history,
        sales_store=sales_store,
        reconciliation_repo=reconciliation_repo,
        coffee_recipe_repo=coffee_recipe_repo,
        domain_product_store=domain_product_store,
        party_names_lookup=party_names_lookup,
        tolerance_seconds=tolerance_seconds,
    )
