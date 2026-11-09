from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.commands import (
    add_domain_product_link,
    create_domain_product,
    link_domain_product,
    remove_domain_product_link,
    set_legacy_ms_code,
)
from src.application.product_identity.models import (
    CatalogProduct,
    DomainProductRejected,
    catalog_codes_of,
)
from src.application.product_identity.resolve import (
    ResolveRecognized,
    resolve_sale_code,
)
from src.domain.product_catalog import ProductUnit


def test_remove_domain_product_link_drops_one_code() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="c1", name="Кофе A", archived=False),
            CatalogProduct(code="c2", name="Кофе B", archived=False),
        )
    )
    product = create_domain_product(
        "Зёрна",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(product.domain_product_id, "c1", store=store, lookup=lookup)
    add_domain_product_link(product.domain_product_id, "c2", store=store, lookup=lookup)
    remove_domain_product_link(product.domain_product_id, "c1", store=store)
    saved = store.get(product.domain_product_id)
    assert saved is not None
    assert catalog_codes_of(saved) == ("c2",)
    assert saved.catalog_code == "c2"
    assert saved.extra_catalog_codes == ()


def test_coffee_ingredient_accepts_two_ms_codes_and_resolves_both() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="c1", name="Кофе A", archived=False),
            CatalogProduct(code="c2", name="Кофе B", archived=False),
        )
    )
    product = create_domain_product(
        "Зёрна",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(product.domain_product_id, "c1", store=store, lookup=lookup)
    add_domain_product_link(product.domain_product_id, "c2", store=store, lookup=lookup)
    saved = store.get(product.domain_product_id)
    assert saved is not None
    assert catalog_codes_of(saved) == ("c1", "c2")
    r1 = resolve_sale_code("c1", store=store, lookup=lookup)
    r2 = resolve_sale_code("c2", store=store, lookup=lookup)
    assert isinstance(r1, ResolveRecognized)
    assert isinstance(r2, ResolveRecognized)
    assert r1.domain_product_id == product.domain_product_id
    assert r2.domain_product_id == product.domain_product_id
    assert r1.catalog_code == "c1"
    assert r2.catalog_code == "c2"


def test_legacy_single_catalog_code_roundtrip() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    product = create_domain_product("Молоко", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)
    saved = store.get(product.domain_product_id)
    assert saved is not None
    assert saved.catalog_code == "2311"
    assert catalog_codes_of(saved) == ("2311",)
    assert saved.kind == "micromarket"
    assert saved.extra_catalog_codes == ()


def test_hidden_holder_still_blocks_code() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="x1", name="X", archived=False),))
    first = create_domain_product(
        "A",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(first.domain_product_id, "x1", store=store, lookup=lookup)
    from src.application.product_identity.commands import hide_domain_product

    hide_domain_product(first.domain_product_id, store=store, contour="coffee")
    second = create_domain_product(
        "B",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    with pytest.raises(DomainProductRejected, match="Карточка уже занята"):
        add_domain_product_link(second.domain_product_id, "x1", store=store, lookup=lookup)


def test_micromarket_rejects_second_link() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="a", name="A", archived=False),
            CatalogProduct(code="b", name="B", archived=False),
        )
    )
    product = create_domain_product("MM", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "a", store=store, lookup=lookup)
    with pytest.raises(DomainProductRejected, match="уже другая карточка|вторую связь"):
        add_domain_product_link(product.domain_product_id, "b", store=store, lookup=lookup)


def test_drink_legacy_ms_code_resolves() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="drink-ms", name="Капучино", archived=False),))
    drink = create_domain_product(
        "Капучино",
        store=store,
        lookup=lookup,
        kind="coffee_drink",
    )
    set_legacy_ms_code(drink.domain_product_id, "drink-ms", store=store, lookup=lookup)
    result = resolve_sale_code("drink-ms", store=store, lookup=lookup)
    assert isinstance(result, ResolveRecognized)
    assert result.domain_product_id == drink.domain_product_id
    assert result.catalog_code == "drink-ms"
