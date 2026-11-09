from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.commands import (
    create_domain_product,
    set_domain_product_packaging,
)
from src.application.product_identity.models import DomainProductRejected
from src.domain.product_catalog import ProductUnit


def test_coffee_ingredient_requires_pack_size() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    with pytest.raises(DomainProductRejected, match="единицу и размер упаковки"):
        create_domain_product(
            "Молоко",
            store=store,
            lookup=lookup,
            kind="coffee_ingredient",
        )
    assert store.writes == 0


def test_upsert_packaging_happy() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    created = create_domain_product(
        "Молоко",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    assert created.unit is ProductUnit.GRAM
    assert created.pack_size == Decimal("1000")

    updated = set_domain_product_packaging(
        created.domain_product_id,
        unit=ProductUnit.MILLILITER,
        pack_size=Decimal("500"),
        store=store,
    )
    assert updated.unit is ProductUnit.MILLILITER
    assert updated.pack_size == Decimal("500")
    saved = store.get(created.domain_product_id)
    assert saved is not None
    assert saved.pack_size == Decimal("500")


def test_set_packaging_rejects_non_positive_pack_size() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    created = create_domain_product(
        "Сахар",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("200"),
    )
    with pytest.raises(DomainProductRejected, match="единицу и размер упаковки"):
        set_domain_product_packaging(
            created.domain_product_id,
            unit=ProductUnit.GRAM,
            pack_size=Decimal("0"),
            store=store,
        )
