from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation import (
    PeriodSnapshotNotReadyError,
    build_period_snapshot,
)
from src.application.inventory_reconciliation.party_names import resolve_frozen_party_names
from src.application.inventory_reconciliation.ports import (
    MachineRevisionHistoryReader,
    MachineSalesStore,
    PeriodPartyNamesLookup,
    ResponsibilityPeriodReconciliationRepository,
    VendingMachineCodeResolver,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.ids import MachineId


@beartype
@dataclass(frozen=True, slots=True)
class RebuildPeriodSnapshots:
    repo: ResponsibilityPeriodReconciliationRepository
    revision_history: MachineRevisionHistoryReader
    form_submission_store: FormSubmissionStore
    sales_store: MachineSalesStore
    coffee_recipe_repo: CoffeeRecipeRepository
    domain_product_store: DomainProductStore
    code_resolver: VendingMachineCodeResolver
    tolerance_seconds: int
    party_names_lookup: PeriodPartyNamesLookup

    @beartype
    def execute(
        self,
        *,
        machine_id: MachineId | None = None,
        all_machines: bool = False,
    ) -> tuple[str, ...]:
        machine_ids = self._machine_ids(machine_id=machine_id, all_machines=all_machines)
        rebuilt: list[str] = []
        for current_machine_id in machine_ids:
            revisions = self.revision_history.list_revisions(current_machine_id)
            for opening, closing in zip(revisions, revisions[1:], strict=False):
                period_id = f"{opening.revision_id.value}:{closing.revision_id.value}"
                try:
                    location_name, technician_name = resolve_frozen_party_names(
                        self.party_names_lookup,
                        machine_id=current_machine_id,
                        technician_id=opening.technician_id,
                        period_id=period_id,
                        existing=self.repo.get_by_period_id(period_id),
                    )
                    snapshot = build_period_snapshot(
                        opening=opening,
                        closing=closing,
                        form_submission_store=self.form_submission_store,
                        revision_history=self.revision_history,
                        sales_store=self.sales_store,
                        coffee_recipe_repo=self.coffee_recipe_repo,
                        domain_product_store=self.domain_product_store,
                        tolerance_seconds=self.tolerance_seconds,
                        location_name=location_name,
                        technician_name=technician_name,
                    )
                except PeriodSnapshotNotReadyError:
                    continue
                self.repo.save(snapshot)
                rebuilt.append(snapshot.period_id)
        return tuple(rebuilt)

    @beartype
    def _machine_ids(
        self,
        *,
        machine_id: MachineId | None,
        all_machines: bool,
    ) -> tuple[MachineId, ...]:
        if machine_id is not None:
            return (machine_id,)
        if not all_machines:
            return ()
        resolved: list[MachineId] = []
        for code in self.code_resolver.list_codes():
            candidate = self.code_resolver.resolve(code)
            if candidate is not None:
                resolved.append(candidate)
        return tuple(resolved)
