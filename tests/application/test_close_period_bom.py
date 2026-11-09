from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.close_period_helpers import (
    CLOSED,
    ClosePeriodTestOptions,
    FakePeriodPartyNamesLookup,
    build_close_period_deps,
    second_revision_event,
)
from tests.application.coffee_bom.bom_fixtures import seed_latte_bom
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.inventory_reconciliation.close_period import (
    CloseResponsibilityPeriodOnRevision,
)
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository


def _build_bom_close_service(
    *,
    recipe_repo: InMemoryCoffeeRecipeRepository | None = None,
    products: FakeDomainProductStore | None = None,
    options: ClosePeriodTestOptions | None = None,
    seed_latte: bool = True,
    seed_bundle_sale: bool = True,
) -> tuple[
    CloseResponsibilityPeriodOnRevision,
    InMemoryCoffeeRecipeRepository,
    FakeDomainProductStore,
]:
    if seed_latte:
        store, repo = seed_latte_bom(products=products, recipes=recipe_repo)
    else:
        store = products if products is not None else FakeDomainProductStore()
        repo = recipe_repo if recipe_repo is not None else InMemoryCoffeeRecipeRepository()
    form_store, history, sales_store, reconciliation_repo = build_close_period_deps(
        options=options
        or ClosePeriodTestOptions(
            sale_occurred_at=None,
            closing_quantity="88",
        ),
    )
    if seed_bundle_sale:
        sales_store.insert_if_absent(
            MachineSale(
                source_id="kv-1",
                machine_id=MachineId("vm-01"),
                product_code="2301",
                quantity=Decimal("1"),
                occurred_at=CLOSED,
                ingested_at=datetime(2026, 6, 8, 11, 0, tzinfo=UTC),
                sale_kind="coffee",
            ),
        )
    service = CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_store,
        revision_history=history,
        sales_store=sales_store,
        reconciliation_repo=reconciliation_repo,
        coffee_recipe_repo=repo,
        domain_product_store=store,
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(),
    )
    return service, repo, store


def test_close_period_expands_bundle_sale_and_computes_delta_on_components() -> None:
    service, _repo, _store = _build_bom_close_service()

    result = service.execute(closing_event=second_revision_event())

    assert result is not None
    assert result.status == "complete"
    assert result.lines[0].calculated == Decimal("90")
    assert result.lines[0].delta == Decimal("-2")
    assert result.sales_lines[0].product_code == "coffee-1"
    assert result.sales_lines[0].quantity == Decimal("30")


def test_close_period_defers_lines_when_only_sales_pending() -> None:
    store, recipe_repo = seed_latte_bom()
    form_store, history, sales_store, reconciliation_repo = build_close_period_deps(
        options=ClosePeriodTestOptions(
            sale_occurred_at=None,
            closing_quantity="88",
        ),
    )
    sales_store.insert_if_absent(
        MachineSale(
            source_id="kv-early",
            machine_id=MachineId("vm-01"),
            product_code="2301",
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 6, 8, 9, 30, tzinfo=UTC),
            sale_kind="coffee",
        ),
    )
    service = CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_store,
        revision_history=history,
        sales_store=sales_store,
        reconciliation_repo=reconciliation_repo,
        coffee_recipe_repo=recipe_repo,
        domain_product_store=store,
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(),
    )

    result = service.execute(closing_event=second_revision_event())

    assert result is not None
    assert result.status == "pending_sales"
    assert result.lines == ()
    assert result.load_count == 1


def test_close_period_pending_when_bundle_not_in_bom() -> None:
    service, _repo, _store = _build_bom_close_service(
        recipe_repo=InMemoryCoffeeRecipeRepository(),
        seed_latte=False,
    )

    result = service.execute(closing_event=second_revision_event())

    assert result is not None
    assert result.status == "pending_sales"
    assert result.sales_lines == ()
    assert result.lines
    assert result.load_count == 1


def test_close_period_log_blocking_reason_bom_when_recipe_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.WARNING,
        logger="src.application.inventory_reconciliation.close_period",
    )
    service, _repo, _store = _build_bom_close_service(
        recipe_repo=InMemoryCoffeeRecipeRepository(),
        seed_latte=False,
    )

    service.execute(closing_event=second_revision_event())

    pending_records = [
        record
        for record in caplog.records
        if record.message == "period_reconciliation_pending_sales"
    ]
    assert pending_records
    assert pending_records[0].blocking_reason == "bom"
    assert pending_records[0].levelno == logging.WARNING


def test_close_period_log_blocking_reason_sales_when_ingest_incomplete(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="src.application.inventory_reconciliation.close_period",
    )
    store, recipe_repo = seed_latte_bom()
    form_store, history, sales_store, reconciliation_repo = build_close_period_deps(
        options=ClosePeriodTestOptions(
            sale_occurred_at=None,
            closing_quantity="88",
        ),
    )
    sales_store.insert_if_absent(
        MachineSale(
            source_id="kv-early",
            machine_id=MachineId("vm-01"),
            product_code="2301",
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 6, 8, 9, 30, tzinfo=UTC),
            sale_kind="coffee",
        ),
    )
    service = CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_store,
        revision_history=history,
        sales_store=sales_store,
        reconciliation_repo=reconciliation_repo,
        coffee_recipe_repo=recipe_repo,
        domain_product_store=store,
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(),
    )

    service.execute(closing_event=second_revision_event())

    pending_records = [
        record
        for record in caplog.records
        if record.message == "period_reconciliation_pending_sales"
    ]
    assert pending_records
    assert pending_records[0].blocking_reason == "sales"
    assert pending_records[0].levelno == logging.INFO


def test_close_period_log_blocking_reason_both_when_bom_and_sales_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.WARNING,
        logger="src.application.inventory_reconciliation.close_period",
    )
    recipe_repo = InMemoryCoffeeRecipeRepository()
    form_store, history, sales_store, reconciliation_repo = build_close_period_deps(
        options=ClosePeriodTestOptions(
            sale_occurred_at=None,
            closing_quantity="88",
        ),
    )
    sales_store.insert_if_absent(
        MachineSale(
            source_id="kv-early",
            machine_id=MachineId("vm-01"),
            product_code="2301",
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 6, 8, 9, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 6, 8, 9, 30, tzinfo=UTC),
            sale_kind="coffee",
        ),
    )
    service = CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_store,
        revision_history=history,
        sales_store=sales_store,
        reconciliation_repo=reconciliation_repo,
        coffee_recipe_repo=recipe_repo,
        domain_product_store=FakeDomainProductStore(),
        tolerance_seconds=0,
        party_names_lookup=FakePeriodPartyNamesLookup(),
    )

    service.execute(closing_event=second_revision_event())

    pending_records = [
        record
        for record in caplog.records
        if record.message == "period_reconciliation_pending_sales"
    ]
    assert pending_records
    assert pending_records[0].blocking_reason == "both"
    assert pending_records[0].levelno == logging.WARNING
