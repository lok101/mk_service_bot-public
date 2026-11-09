from __future__ import annotations

from decimal import Decimal

from scripts.unhide_coffee_domain_products import unhide_hidden_coffee
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.commands import (
    create_domain_product,
    hide_domain_product,
)
from src.domain.product_catalog import ProductUnit


def test_cutover_unhide_coffee_idempotent() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    coffee = create_domain_product(
        "Зёрна",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    create_domain_product("MM", store=store, lookup=lookup)
    hide_domain_product(coffee.domain_product_id, store=store, contour="coffee")
    assert unhide_hidden_coffee(store=store) == 1
    assert unhide_hidden_coffee(store=store) == 0
    saved = store.get(coffee.domain_product_id)
    assert saved is not None
    assert saved.hidden is False
