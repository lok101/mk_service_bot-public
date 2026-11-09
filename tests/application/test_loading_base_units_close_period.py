from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.close_period_helpers import (
    CLOSED,
    INSIDE,
    MACHINE_ID,
    OPENED,
    ClosePeriodTestOptions,
    FakePeriodPartyNamesLookup,
    build_close_period_deps,
    coffee_line,
    first_revision_event,
    loading_coffee_line,
    loading_event,
    second_revision_event,
)
from tests.application.coffee_bom.bom_fixtures import seed_latte_bom
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.form_submissions.outbox_errors import NonRetryableOutboxError
from src.application.inventory_reconciliation.close_period import (
    CloseResponsibilityPeriodOnRevision,
)
from src.domain.form_submission import FormAnswer, FrozenInventoryLine, FrozenProductSpec
from src.domain.machine_sales import MachineSale
from src.domain.product_catalog import ProductUnit, default_moysklad_quantity_factor
from src.infrastructure.form_submissions.memory import InMemoryFormSubmissionStore
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineRevisionHistoryReader,
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
)


def _gram_revision_line(quantity: str) -> FrozenInventoryLine:
    unit = ProductUnit.GRAM
    return FrozenInventoryLine(
        form_title="Кофе",
        product_spec=FrozenProductSpec(
            product_code="coffee-1",
            name="Кофе",
            unit=unit,
            pack_size=None,
            moysklad_quantity_factor=default_moysklad_quantity_factor(unit),
        ),
        quantity=Decimal(quantity),
    )


def _build_service_with_loading_packages(
    *,
    opening_quantity: str,
    closing_quantity: str,
    packages: str,
    pack_size: str,
) -> CloseResponsibilityPeriodOnRevision:
    form_store = InMemoryFormSubmissionStore()
    history = InMemoryMachineRevisionHistoryReader()
    sales_store = InMemoryMachineSalesStore()
    repo = InMemoryPeriodReconciliationRepository()
    first_revision = first_revision_event()
    second_revision = second_revision_event()
    loading = loading_event()
    history.add_revision(first_revision)
    history.add_revision(second_revision)
    history.add_loading(loading)

    opening_line = _gram_revision_line(opening_quantity)
    closing_line = _gram_revision_line(closing_quantity)
    rev1_pending = form_store.save_pending(
        form_token=first_revision.form_token,
        form_id=first_revision.form_id,
        purpose="revision",
        technician_id=first_revision.technician_id,
        machine_id=MACHINE_ID,
        submitted_at=OPENED,
        answers=(FormAnswer(title="Кофе", value=opening_quantity),),
        validated_lines=(opening_line,),
    )
    form_store.mark_accepted(
        rev1_pending.submission_id,
        event_id=first_revision.event_id.value,
        occurred_at=OPENED,
        revision_id=first_revision.revision_id.value,
    )
    rev2_pending = form_store.save_pending(
        form_token=second_revision.form_token,
        form_id=second_revision.form_id,
        purpose="revision",
        technician_id=second_revision.technician_id,
        machine_id=MACHINE_ID,
        submitted_at=CLOSED,
        answers=(FormAnswer(title="Кофе", value=closing_quantity),),
        validated_lines=(closing_line,),
    )
    form_store.mark_accepted(
        rev2_pending.submission_id,
        event_id=second_revision.event_id.value,
        occurred_at=CLOSED,
        revision_id=second_revision.revision_id.value,
    )
    load_pending = form_store.save_pending(
        form_token=loading.form_token,
        form_id=loading.form_id,
        purpose="loading",
        technician_id=loading.technician_id,
        machine_id=MACHINE_ID,
        submitted_at=INSIDE,
        answers=(FormAnswer(title="Кофе", value=packages),),
        validated_lines=(loading_coffee_line(packages=packages, pack_size=pack_size),),
    )
    form_store.mark_accepted(
        load_pending.submission_id,
        event_id=loading.event_id.value,
        occurred_at=INSIDE,
    )
    sales_store.insert_if_absent(
        MachineSale(
            source_id="kv-1",
            machine_id=MACHINE_ID,
            product_code="2301",
            quantity=Decimal("0"),
            occurred_at=CLOSED,
            ingested_at=CLOSED,
            sale_kind="coffee",
        ),
    )
    products, recipe_repo = seed_latte_bom(coffee_qty="1")
    return CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_store,
        revision_history=history,
        sales_store=sales_store,
        reconciliation_repo=repo,
        coffee_recipe_repo=recipe_repo,
        domain_product_store=products,
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(),
    )


def test_close_period_loads_in_base_units_packages_times_pack_size() -> None:
    service = _build_service_with_loading_packages(
        opening_quantity="1000",
        closing_quantity="5000",
        packages="4",
        pack_size="1000",
    )
    result = service.execute(closing_event=second_revision_event())
    assert result is not None
    line = result.lines[0]
    assert line.loads_total == Decimal("4000")
    assert line.calculated == Decimal("5000")
    assert line.delta == Decimal("0")
    assert len(result.load_lines) == 1
    assert result.load_lines[0].input_quantity == Decimal("4")
    assert result.load_lines[0].pack_size == Decimal("1000")
    assert result.load_lines[0].base_quantity == Decimal("4000")


def test_raises_nonretryable_when_loading_pack_size_missing() -> None:
    form_store, history, sales_store, repo = build_close_period_deps(
        options=ClosePeriodTestOptions(
            sale_occurred_at=CLOSED,
            accept_loading=False,
        ),
    )
    loading = loading_event()
    load_pending = form_store.save_pending(
        form_token=loading.form_token,
        form_id=loading.form_id,
        purpose="loading",
        technician_id=loading.technician_id,
        machine_id=MACHINE_ID,
        submitted_at=INSIDE,
        answers=(FormAnswer(title="Кофе", value="2"),),
        validated_lines=(coffee_line("2"),),
    )
    form_store.mark_accepted(
        load_pending.submission_id,
        event_id=loading.event_id.value,
        occurred_at=INSIDE,
    )
    service = CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_store,
        revision_history=history,
        sales_store=sales_store,
        reconciliation_repo=repo,
        coffee_recipe_repo=InMemoryCoffeeRecipeRepository(),
        domain_product_store=FakeDomainProductStore(),
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(),
    )
    with pytest.raises(NonRetryableOutboxError, match="Pack size must be configured"):
        service.execute(closing_event=second_revision_event())
