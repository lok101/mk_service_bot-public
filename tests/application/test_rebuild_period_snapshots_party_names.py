from __future__ import annotations

from tests.application.close_period_helpers import (
    MACHINE_ID,
    FakePeriodPartyNamesLookup,
    _default_coffee_bom,
    build_close_period_deps,
)

from src.application.inventory_reconciliation.rebuild_periods import RebuildPeriodSnapshots
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver


def test_rebuild_skips_period_when_party_names_missing() -> None:
    form_store, history, sales_store, repo = build_close_period_deps()
    _products, _recipes = _default_coffee_bom()

    use_case = RebuildPeriodSnapshots(
        repo=repo,
        revision_history=history,
        form_submission_store=form_store,
        sales_store=sales_store,
        coffee_recipe_repo=_recipes,
        domain_product_store=_products,
        code_resolver=MappingVendingMachineCodeResolver({"vm-01": MACHINE_ID}),
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(location=None, technician="Tech"),
    )

    rebuilt = use_case.execute(machine_id=MACHINE_ID)

    assert rebuilt == ()
    assert repo.get_by_period_id("rev-1:rev-2") is None


def test_rebuild_persists_party_names_when_lookup_ok() -> None:
    form_store, history, sales_store, repo = build_close_period_deps()
    _products, _recipes = _default_coffee_bom()

    use_case = RebuildPeriodSnapshots(
        repo=repo,
        revision_history=history,
        form_submission_store=form_store,
        sales_store=sales_store,
        coffee_recipe_repo=_recipes,
        domain_product_store=_products,
        code_resolver=MappingVendingMachineCodeResolver({"vm-01": MACHINE_ID}),
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(
            location="  Rebuild Loc  ",
            technician="  Rebuild Tech  ",
        ),
    )

    rebuilt = use_case.execute(machine_id=MACHINE_ID)

    assert rebuilt == ("rev-1:rev-2",)
    saved = repo.get_by_period_id("rev-1:rev-2")
    assert saved is not None
    assert saved.location_name == "Rebuild Loc"
    assert saved.technician_name == "Rebuild Tech"
