from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.coffee_bom.bom_fixtures import seed_latte_bom
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.inventory_reconciliation.sales_prepare import (
    prepare_coffee_sales_for_reconciliation,
)
from src.domain.ids import MachineId
from src.domain.machine_sales import MachineSale
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository

_INSIDE = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
_INGESTED = datetime(2026, 6, 8, 11, 0, tzinfo=UTC)


def test_prepare_expands_coffee_sales_for_reconciliation() -> None:
    machine_sales = (
        MachineSale(
            source_id="kv-1",
            machine_id=MachineId("vm-01"),
            product_code="2301",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
            sale_kind="coffee",
        ),
    )
    products, repo = seed_latte_bom(coffee_qty="12.5")
    prepared = prepare_coffee_sales_for_reconciliation(
        machine_sales,
        recipe_repo=repo,
        products=products,
    )
    assert prepared.bom_coverage_ok is True
    assert prepared.period_sales[0].product_code == "coffee-1"
    assert prepared.frozen_sales[0].product_code == "coffee-1"


def test_prepare_ignores_snack_sales() -> None:
    machine_sales = (
        MachineSale(
            source_id="kv-1",
            machine_id=MachineId("vm-01"),
            product_code="2101",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
            sale_kind="snack",
        ),
    )
    prepared = prepare_coffee_sales_for_reconciliation(
        machine_sales,
        recipe_repo=InMemoryCoffeeRecipeRepository(),
        products=FakeDomainProductStore(),
    )
    assert prepared.period_sales == ()
    assert prepared.bom_coverage_ok is True


def test_prepare_ignores_unknown_sale_kind() -> None:
    machine_sales = (
        MachineSale(
            source_id="kv-1",
            machine_id=MachineId("vm-01"),
            product_code="2301",
            quantity=Decimal("1"),
            occurred_at=_INSIDE,
            ingested_at=_INGESTED,
            sale_kind="unknown",
        ),
    )
    prepared = prepare_coffee_sales_for_reconciliation(
        machine_sales,
        recipe_repo=InMemoryCoffeeRecipeRepository(),
        products=FakeDomainProductStore(),
    )
    assert prepared.period_sales == ()
    assert prepared.bom_coverage_ok is True
