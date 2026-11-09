from __future__ import annotations

from decimal import Decimal

from tests.application.close_period_helpers import (
    CLOSED,
    OPENED,
    ClosePeriodTestOptions,
    _default_coffee_bom,
    build_close_period_deps,
    gram_revision_line,
)

from src.application.inventory_reconciliation.period_snapshot_recalculate import (
    recalculate_snapshot,
)
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation


def test_recalculate_preserves_party_names() -> None:
    form_store, history, sales_store, _repo = build_close_period_deps(
        options=ClosePeriodTestOptions(
            opening_lines=(gram_revision_line(quantity="1000"),),
            closing_lines=(gram_revision_line(quantity="5000"),),
            loading_packages="4",
            loading_pack_size="1000",
            sale_occurred_at=None,
        ),
    )
    snapshot = ResponsibilityPeriodReconciliation(
        period_id="rev-1:rev-2",
        machine_id=MachineId("vm-01"),
        responsible_technician_id=TechnicianId("tech-a"),
        opening_revision_id=RevisionId("rev-1"),
        closing_revision_id=RevisionId("rev-2"),
        opened_at=OPENED,
        closed_at=CLOSED,
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
        sales_lines=(),
        load_count=1,
        status="complete",
        load_lines=(),
        ledger_posted=False,
        reconciled=False,
        location_name="Frozen Loc",
        technician_name="Frozen Tech",
    )

    _products, _recipes = _default_coffee_bom()

    updated = recalculate_snapshot(
        snapshot,
        force=False,
        sales_store=sales_store,
        coffee_recipe_repo=_recipes,
        domain_product_store=_products,
        form_submission_store=form_store,
        revision_history=history,
        tolerance_seconds=0,
    )

    assert updated.location_name == "Frozen Loc"
    assert updated.technician_name == "Frozen Tech"
