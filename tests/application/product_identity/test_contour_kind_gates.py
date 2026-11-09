from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.commands import (
    allocate_domain_number,
    create_domain_product,
    hide_domain_product,
    unhide_domain_product,
)
from src.application.product_identity.models import (
    CatalogProduct,
    DomainProductRejected,
)
from src.domain.product_catalog import ProductUnit
from src.interfaces.admin.planogram_product_options import planogram_product_options


def test_unhide_domain_product_clears_hidden() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    product = create_domain_product(
        "Зёрна",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    hide_domain_product(product.domain_product_id, store=store, contour="coffee")
    hidden = store.get(product.domain_product_id)
    assert hidden is not None
    assert hidden.hidden is True
    restored = unhide_domain_product(product.domain_product_id, store=store)
    assert restored.hidden is False
    assert store.get(product.domain_product_id) is not None
    assert store.get(product.domain_product_id).hidden is False  # type: ignore[union-attr]


def test_hide_rejects_coffee_kind() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    product = create_domain_product(
        "Зёрна",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    with pytest.raises(DomainProductRejected):
        hide_domain_product(product.domain_product_id, store=store)


def test_allocate_still_global_across_kinds() -> None:
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
    mm = create_domain_product("Молоко MM", store=store, lookup=lookup)
    assert coffee.number.startswith("d-")
    assert mm.number.startswith("d-")
    assert coffee.number != mm.number
    next_number = allocate_domain_number(
        store.numbers(),
        collides=lookup.number_collides,
    )
    coffee_n = int(coffee.number.removeprefix("d-"))
    mm_n = int(mm.number.removeprefix("d-"))
    next_n = int(next_number.removeprefix("d-"))
    assert next_n == max(coffee_n, mm_n) + 1


def test_planogram_options_exclude_coffee() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="1", name="X", archived=False),))
    create_domain_product("MM товар", store=store, lookup=lookup)
    create_domain_product(
        "Кофейный",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    options = planogram_product_options(store)
    names = {row.name for row in options}
    assert "MM товар" in names
    assert "Кофейный" not in names
