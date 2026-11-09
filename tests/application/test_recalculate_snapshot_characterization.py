from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from tests.application.close_period_helpers import (
    CLOSED,
    INSIDE,
    OPENED,
    ClosePeriodTestOptions,
    _default_coffee_bom,
    build_close_period_deps,
    coffee_line,
    gram_revision_line,
)

from src.application.form_submissions.outbox_errors import NonRetryableOutboxError
from src.application.inventory_reconciliation.period_snapshot_recalculate import (
    recalculate_snapshot,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import (
    FrozenSalesLine,
    ResponsibilityPeriodReconciliation,
)
from src.domain.machine_sales import MachineSale


def _deps(options: ClosePeriodTestOptions | None = None):
    form_store, history, sales_store, _repo = build_close_period_deps(options=options)
    return form_store, history, sales_store


def _snapshot(**overrides) -> ResponsibilityPeriodReconciliation:
    base = ResponsibilityPeriodReconciliation(
        period_id="rev-1:rev-2",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=OPENED,
        closed_at=CLOSED,
        lines=(),
        sales_lines=(),
        load_count=0,
        status="pending_sales",
    )
    return replace(base, **overrides)


def _call(snapshot, *, force=False, options=None):
    form_store, history, sales_store = _deps(options)
    _products, _recipes = _default_coffee_bom()

    return recalculate_snapshot(
        snapshot,
        force=force,
        sales_store=sales_store,
        coffee_recipe_repo=_recipes,
        domain_product_store=_products,
        form_submission_store=form_store,
        revision_history=history,
        tolerance_seconds=0,
    )


def test_recalculate_skips_when_posted_and_not_forced() -> None:
    snapshot = _snapshot(status="complete", ledger_posted=True)
    result = _call(snapshot, force=False)
    assert result is snapshot


def test_recalculate_skips_when_reconciled_and_not_forced() -> None:
    snapshot = _snapshot(status="complete", reconciled=True)
    result = _call(snapshot, force=False)
    assert result is snapshot


def test_recalculate_empty_lines_still_pending_updates_sales_and_status() -> None:
    snapshot = _snapshot(status="pending_sales", lines=())
    result = _call(snapshot, options=ClosePeriodTestOptions(sale_occurred_at=None))
    assert result.lines == ()
    assert result.status == "pending_sales"


def test_recalculate_empty_lines_complete_runs_full_recalc() -> None:
    snapshot = _snapshot(status="pending_sales", lines=())
    result = _call(snapshot, options=ClosePeriodTestOptions(sale_occurred_at=CLOSED))
    assert result.status == "complete"
    assert len(result.lines) == 1
    assert result.load_count == 1


def test_recalculate_empty_lines_complete_raises_on_domain_error() -> None:
    snapshot = _snapshot(status="pending_sales", lines=())
    with pytest.raises(NonRetryableOutboxError, match="DuplicateProductCodeInStock"):
        _call(
            snapshot,
            options=ClosePeriodTestOptions(
                sale_occurred_at=CLOSED,
                opening_lines=(coffee_line("50"), coffee_line("50")),
            ),
        )


def test_recalculate_force_runs_full_recalc_for_posted() -> None:
    snapshot = _snapshot(
        status="complete",
        ledger_posted=True,
        lines=(
            ReconciliationLine(
                product_code="coffee-1",
                actual_prev=Decimal("100"),
                actual=Decimal("90"),
                calculated=Decimal("90"),
                delta=Decimal("0"),
            ),
        ),
    )
    result = _call(snapshot, force=True, options=ClosePeriodTestOptions(sale_occurred_at=CLOSED))
    assert result.status == "complete"
    assert len(result.lines) == 1


def test_recalculate_with_lines_no_load_lines_backfills_loads() -> None:
    snapshot = _snapshot(
        status="complete",
        lines=(
            ReconciliationLine(
                product_code="coffee-1",
                actual_prev=Decimal("1000"),
                actual=Decimal("5000"),
                calculated=Decimal("1004"),
                delta=Decimal("3996"),
                loads_total=Decimal("4"),
                sales_total=Decimal("0"),
            ),
        ),
        load_count=1,
        load_lines=(),
    )
    options = ClosePeriodTestOptions(
        opening_lines=(gram_revision_line(quantity="1000"),),
        closing_lines=(gram_revision_line(quantity="5000"),),
        loading_packages="4",
        loading_pack_size="1000",
        sale_occurred_at=None,
    )
    result = _call(snapshot, options=options)
    assert len(result.load_lines) == 1
    assert result.load_lines[0].base_quantity == Decimal("4000")


def test_recalculate_with_lines_and_load_lines_recomputes_from_frozen() -> None:
    snapshot = _snapshot(
        status="pending_sales",
        lines=(
            ReconciliationLine(
                product_code="coffee-1",
                actual_prev=Decimal("100"),
                actual=Decimal("90"),
                calculated=Decimal("90"),
                delta=Decimal("0"),
            ),
        ),
        sales_lines=(
            FrozenSalesLine(
                product_code="coffee-1",
                quantity=Decimal("30"),
                occurred_at=INSIDE,
                source_id="kv-inside",
            ),
        ),
        load_count=1,
    )
    form_store, history, sales_store = _deps()
    sales_store.insert_if_absent(
        MachineSale(
            source_id="kv-inside",
            machine_id=MachineId("vm-01"),
            product_code="coffee-1",
            quantity=Decimal("30"),
            occurred_at=INSIDE,
            ingested_at=CLOSED,
            sale_kind="coffee",
        ),
    )
    _products, _recipes = _default_coffee_bom()

    result = recalculate_snapshot(
        snapshot,
        sales_store=sales_store,
        coffee_recipe_repo=_recipes,
        domain_product_store=_products,
        form_submission_store=form_store,
        revision_history=history,
        tolerance_seconds=0,
    )
    assert len(result.lines) == 1
