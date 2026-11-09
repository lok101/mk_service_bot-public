from __future__ import annotations

from dataclasses import replace

from beartype import beartype

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions import NonRetryableOutboxError
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation.period_snapshot_helpers import (
    PeriodReconciliationDomainError,
    _compute_reconciliation_lines,
    _loads_in_window,
    _log_domain_error,
    _log_pending_reconciliation,
    _period_loads_from_frozen,
    _stock_from_lines,
)
from src.application.inventory_reconciliation.ports import (
    MachineRevisionHistoryReader,
    MachineSalesStore,
)
from src.application.inventory_reconciliation.sales_prepare import (
    PreparedCoffeeSales,
    prepare_coffee_sales_for_reconciliation,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.inventory_reconciliation.calculate import calculate_period_reconciliation
from src.domain.inventory_reconciliation.coverage import (
    ReconciliationStatus,
    resolve_reconciliation_status,
)
from src.domain.inventory_reconciliation.snapshot import (
    ResponsibilityPeriodReconciliation,
)
from src.domain.machine_operations.events import RevisionCompleted


@beartype
def _find_revision_pair(
    snapshot: ResponsibilityPeriodReconciliation,
    revision_history: MachineRevisionHistoryReader,
) -> tuple[RevisionCompleted, RevisionCompleted]:
    revisions = revision_history.list_revisions(snapshot.machine_id)
    opening = next(
        (
            revision
            for revision in revisions
            if revision.revision_id == snapshot.opening_revision_id
        ),
        None,
    )
    closing = next(
        (
            revision
            for revision in revisions
            if revision.revision_id == snapshot.closing_revision_id
        ),
        None,
    )
    if opening is None or closing is None:
        raise NonRetryableOutboxError(
            f"Revision pair not found for period {snapshot.period_id}",
        )
    return opening, closing


@beartype
def _full_recalculate_from_submissions(
    snapshot: ResponsibilityPeriodReconciliation,
    *,
    prepared: PreparedCoffeeSales,
    status: ReconciliationStatus,
    form_submission_store: FormSubmissionStore,
    revision_history: MachineRevisionHistoryReader,
) -> ResponsibilityPeriodReconciliation:
    opening, closing = _find_revision_pair(snapshot, revision_history)
    opening_submission = form_submission_store.get_by_event_id(opening.event_id.value)
    closing_submission = form_submission_store.get_by_event_id(closing.event_id.value)
    if opening_submission is None:
        raise NonRetryableOutboxError(
            f"Opening revision form submission was not found for event {opening.event_id.value}",
        )
    if closing_submission is None:
        raise NonRetryableOutboxError(
            f"Closing revision form submission was not found for event {closing.event_id.value}",
        )
    loads, frozen_loads = _loads_in_window(
        revision_history.list_loadings(snapshot.machine_id),
        form_submission_store,
        opened_at=snapshot.opened_at,
        closed_at=snapshot.closed_at,
    )
    # Domain/NonRetryable ошибки из расчёта не глотать: иначе status=complete + lines=()
    # → refresh → PostPeriodAccountability с пустой дельтой и mark_ledger_posted.
    lines = _compute_reconciliation_lines(
        opening_submission=opening_submission,
        closing_submission=closing_submission,
        loads=loads,
        prepared=prepared,
        opened_at=snapshot.opened_at,
        closed_at=snapshot.closed_at,
        period_id=snapshot.period_id,
        machine_id=snapshot.machine_id,
    )
    return replace(
        snapshot,
        lines=lines,
        sales_lines=prepared.frozen_sales,
        status=status,
        load_count=len(loads),
        load_lines=frozen_loads,
    )


@beartype
def recalculate_snapshot(
    snapshot: ResponsibilityPeriodReconciliation,
    *,
    force: bool = False,
    sales_store: MachineSalesStore,
    coffee_recipe_repo: CoffeeRecipeRepository,
    domain_product_store: DomainProductStore,
    form_submission_store: FormSubmissionStore,
    revision_history: MachineRevisionHistoryReader,
    tolerance_seconds: int,
) -> ResponsibilityPeriodReconciliation:
    if (snapshot.ledger_posted or snapshot.reconciled) and not force:
        return snapshot

    raw_sales = sales_store.find_in_window(
        snapshot.machine_id,
        opened_at=snapshot.opened_at,
        closed_at=snapshot.closed_at,
    )
    prepared = prepare_coffee_sales_for_reconciliation(
        raw_sales,
        recipe_repo=coffee_recipe_repo,
        products=domain_product_store,
    )
    machine_last = sales_store.last_occurred_at(snapshot.machine_id)
    global_cursor = sales_store.load_global_cursor()
    status = resolve_reconciliation_status(
        closed_at=snapshot.closed_at,
        machine_last_occurred_at=machine_last,
        global_cursor=global_cursor,
        tolerance_seconds=tolerance_seconds,
        bom_coverage_ok=prepared.bom_coverage_ok,
    )
    if status == "pending_sales":
        _log_pending_reconciliation(
            period_id=snapshot.period_id,
            machine_id=snapshot.machine_id,
            closed_at=snapshot.closed_at,
            machine_last_occurred_at=machine_last,
            global_cursor=global_cursor,
            tolerance_seconds=tolerance_seconds,
            bom_coverage_ok=prepared.bom_coverage_ok,
            unresolved_bundle_codes=prepared.unresolved_bundle_codes,
        )

    if not snapshot.lines and status == "complete":
        return _full_recalculate_from_submissions(
            snapshot,
            prepared=prepared,
            status=status,
            form_submission_store=form_submission_store,
            revision_history=revision_history,
        )

    if not snapshot.lines:
        return replace(snapshot, sales_lines=prepared.frozen_sales, status=status)

    if force:
        return _full_recalculate_from_submissions(
            snapshot,
            prepared=prepared,
            status=status,
            form_submission_store=form_submission_store,
            revision_history=revision_history,
        )

    if not snapshot.load_lines:
        loads, frozen_loads = _loads_in_window(
            revision_history.list_loadings(snapshot.machine_id),
            form_submission_store,
            opened_at=snapshot.opened_at,
            closed_at=snapshot.closed_at,
        )
        load_lines_out = frozen_loads
        load_count_out = len(loads)
    else:
        loads = _period_loads_from_frozen(snapshot.load_lines)
        load_lines_out = snapshot.load_lines
        load_count_out = snapshot.load_count

    result = calculate_period_reconciliation(
        actual_prev=_stock_from_lines(snapshot.lines, stock_field="actual_prev"),
        actual=_stock_from_lines(snapshot.lines, stock_field="actual"),
        loads=loads,
        sales=prepared.period_sales,
        opened_at=snapshot.opened_at,
        closed_at=snapshot.closed_at,
    )
    if isinstance(result, PeriodReconciliationDomainError):
        _log_domain_error(
            error=result,
            period_id=snapshot.period_id,
            machine_id=snapshot.machine_id,
        )
        return replace(snapshot, sales_lines=prepared.frozen_sales, status=status)

    lines = tuple(result.lines_by_product[code] for code in sorted(result.lines_by_product))
    return replace(
        snapshot,
        lines=lines,
        sales_lines=prepared.frozen_sales,
        status=status,
        load_lines=load_lines_out,
        load_count=load_count_out,
    )
