from __future__ import annotations

from dataclasses import dataclass

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions import NonRetryableOutboxError
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation.period_errors import PeriodSnapshotNotReadyError
from src.application.inventory_reconciliation.period_snapshot_helpers import (
    _compute_reconciliation_lines,
    _loads_in_window,
    _log_pending_reconciliation,
)
from src.application.inventory_reconciliation.ports import (
    MachineRevisionHistoryReader,
    MachineSalesStore,
)
from src.application.inventory_reconciliation.sales_prepare import (
    prepare_coffee_sales_for_reconciliation,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.inventory_reconciliation.coverage import resolve_reconciliation_status
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_operations.events import RevisionCompleted

__all__ = ["PeriodSnapshotBuilder"]


@beartype
@dataclass(frozen=True, slots=True)
class PeriodSnapshotBuilder:
    form_submission_store: FormSubmissionStore
    revision_history: MachineRevisionHistoryReader
    sales_store: MachineSalesStore
    coffee_recipe_repo: CoffeeRecipeRepository
    domain_product_store: DomainProductStore
    tolerance_seconds: int

    @beartype
    def build_from_revision_pair(
        self,
        opening: RevisionCompleted,
        closing: RevisionCompleted,
        *,
        location_name: str,
        technician_name: str,
    ) -> ResponsibilityPeriodReconciliation:
        period_id = f"{opening.revision_id.value}:{closing.revision_id.value}"

        opening_submission = self.form_submission_store.get_by_event_id(opening.event_id.value)
        if opening_submission is None:
            raise NonRetryableOutboxError(
                "Opening revision form submission was not found for event "
                f"{opening.event_id.value}",
            )

        closing_submission = self.form_submission_store.get_by_event_id(closing.event_id.value)
        if closing_submission is None:
            raise PeriodSnapshotNotReadyError(
                "Closing revision form submission was not found for event "
                f"{closing.event_id.value}",
            )

        opened_at = opening.completed_at
        closed_at = closing.completed_at
        loads, frozen_loads = _loads_in_window(
            self.revision_history.list_loadings(closing.machine_id),
            self.form_submission_store,
            opened_at=opened_at,
            closed_at=closed_at,
        )
        raw_sales = self.sales_store.find_in_window(
            closing.machine_id,
            opened_at=opened_at,
            closed_at=closed_at,
        )
        prepared = prepare_coffee_sales_for_reconciliation(
            raw_sales,
            recipe_repo=self.coffee_recipe_repo,
            products=self.domain_product_store,
        )
        machine_last = self.sales_store.last_occurred_at(closing.machine_id)
        global_cursor = self.sales_store.load_global_cursor()
        status = resolve_reconciliation_status(
            closed_at=closed_at,
            machine_last_occurred_at=machine_last,
            global_cursor=global_cursor,
            tolerance_seconds=self.tolerance_seconds,
            bom_coverage_ok=prepared.bom_coverage_ok,
        )
        if status == "pending_sales":
            _log_pending_reconciliation(
                period_id=period_id,
                machine_id=closing.machine_id,
                closed_at=closed_at,
                machine_last_occurred_at=machine_last,
                global_cursor=global_cursor,
                tolerance_seconds=self.tolerance_seconds,
                bom_coverage_ok=prepared.bom_coverage_ok,
                unresolved_bundle_codes=prepared.unresolved_bundle_codes,
            )

        defer_lines = status == "pending_sales" and prepared.bom_coverage_ok
        if defer_lines:
            lines: tuple[ReconciliationLine, ...] = ()
        else:
            lines = _compute_reconciliation_lines(
                opening_submission=opening_submission,
                closing_submission=closing_submission,
                loads=loads,
                prepared=prepared,
                opened_at=opened_at,
                closed_at=closed_at,
                period_id=period_id,
                machine_id=closing.machine_id,
            )

        return ResponsibilityPeriodReconciliation(
            period_id=period_id,
            machine_id=closing.machine_id,
            responsible_technician_id=opening.technician_id,
            opening_revision_id=opening.revision_id,
            closing_revision_id=closing.revision_id,
            opened_at=opened_at,
            closed_at=closed_at,
            lines=lines,
            sales_lines=prepared.frozen_sales,
            load_count=len(loads),
            status=status,
            load_lines=frozen_loads,
            location_name=location_name,
            technician_name=technician_name,
        )
