from __future__ import annotations

from datetime import timedelta

from tests.application.close_period_helpers import (
    CLOSED,
    MACHINE_ID,
    FakePeriodPartyNamesLookup,
    _default_coffee_bom,
    build_close_period_deps,
    coffee_line,
)

from src.application.inventory_reconciliation.rebuild_periods import RebuildPeriodSnapshots
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.domain.form_submission import FormAnswer
from src.domain.ids import EventId, RevisionId, TechnicianId
from src.domain.machine_operations.events import RevisionCompleted
from src.domain.models import RevisionSource

THIRD = CLOSED + timedelta(days=7)


def third_revision_event() -> RevisionCompleted:
    return RevisionCompleted(
        event_id=EventId("evt-rev-3"),
        revision_id=RevisionId("rev-3"),
        technician_id=TechnicianId("tech-a"),
        machine_id=MACHINE_ID,
        completed_at=THIRD,
        occurred_at=THIRD,
        source=RevisionSource.GOOGLE_FORM,
        form_id="form-rev",
        form_token="token-rev-3",
    )


def test_rebuild_creates_snapshot_per_revision_pair() -> None:
    form_store, history, sales_store, repo = build_close_period_deps()
    third = third_revision_event()
    history.add_revision(third)
    rev3_pending = form_store.save_pending(
        form_token=third.form_token,
        form_id=third.form_id,
        purpose="revision",
        technician_id=third.technician_id,
        machine_id=MACHINE_ID,
        submitted_at=THIRD,
        answers=(FormAnswer(title="Кофе", value="85"),),
        validated_lines=(coffee_line("85"),),
    )
    form_store.mark_accepted(
        rev3_pending.submission_id,
        event_id=third.event_id.value,
        occurred_at=THIRD,
        revision_id=third.revision_id.value,
    )

    _products, _recipes = _default_coffee_bom()

    use_case = RebuildPeriodSnapshots(
        repo=repo,
        revision_history=history,
        form_submission_store=form_store,
        sales_store=sales_store,
        coffee_recipe_repo=_recipes,
        domain_product_store=_products,
        code_resolver=MappingVendingMachineCodeResolver({"vm-01": MACHINE_ID}),
        tolerance_seconds=900,
        party_names_lookup=FakePeriodPartyNamesLookup(),
    )
    rebuilt = use_case.execute(all_machines=True)
    assert sorted(rebuilt) == ["rev-1:rev-2", "rev-2:rev-3"]
