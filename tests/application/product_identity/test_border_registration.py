from __future__ import annotations

from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.border_registration import (
    BorderQueueDecision,
    MemoryBorderRegistrationStore,
    apply_border_queue,
    border_status,
    ignore_border_code,
    note_unregistered_codes,
    unregistered_codes_among,
)
from src.application.product_identity.commands import (
    add_domain_product_link,
    create_domain_product,
)
from src.application.product_identity.models import (
    CARD_TAKEN_TEXT,
    CatalogProduct,
    DomainProductRejected,
)
from src.domain.product_catalog import ProductUnit


def test_ignore_clears_unregistered_and_is_idempotent() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    assert border_status("new1", products=products, border=border) == "unregistered"
    first = ignore_border_code("new1", products=products, border=border)
    second = ignore_border_code("new1", products=products, border=border)
    assert first.ignored is True
    assert second.ignored is True
    assert border_status("new1", products=products, border=border) == "ignored"


def test_link_makes_status_linked() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="c1", name="C", archived=False),))
    product = create_domain_product(
        "Ингр",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(product.domain_product_id, "c1", store=products, lookup=lookup)
    assert border_status("c1", products=products, border=border) == "linked"


def test_queue_without_window_docs_still_lists_unregistered() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    found = unregistered_codes_among(("a", "b", "a"), products=products, border=border)
    assert found == ("a", "b")


def test_ignore_rejects_already_linked_code() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="c1", name="C", archived=False),))
    product = create_domain_product(
        "Ингр",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(product.domain_product_id, "c1", store=products, lookup=lookup)
    with pytest.raises(DomainProductRejected, match="занята"):
        ignore_border_code("c1", products=products, border=border)


def test_apply_border_queue_mix_link_and_ignore() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="link-1", name="Milk", archived=False),
            CatalogProduct(code="ign-1", name="Skip", archived=False),
        )
    )
    note_unregistered_codes(("link-1", "ign-1"), products=products, border=border)
    ingredient = create_domain_product(
        "MilkDom",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    apply_border_queue(
        (
            BorderQueueDecision(
                ms_code="link-1",
                domain_product_id=ingredient.domain_product_id,
            ),
            BorderQueueDecision(ms_code="ign-1", ignored=True),
        ),
        products=products,
        border=border,
        lookup=lookup,
    )
    assert border_status("link-1", products=products, border=border) == "linked"
    assert border_status("ign-1", products=products, border=border) == "ignored"


def test_apply_border_queue_empty_is_noop() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup(())
    apply_border_queue((), products=products, border=border, lookup=lookup)


def test_apply_border_queue_skips_undecided_rows() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="link-1", name="Milk", archived=False),
            CatalogProduct(code="skip-1", name="Later", archived=False),
            CatalogProduct(code="ign-1", name="Skip", archived=False),
        )
    )
    note_unregistered_codes(("link-1", "skip-1", "ign-1"), products=products, border=border)
    ingredient = create_domain_product(
        "MilkDom",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    apply_border_queue(
        (
            BorderQueueDecision(
                ms_code="link-1",
                domain_product_id=ingredient.domain_product_id,
            ),
            BorderQueueDecision(ms_code="skip-1"),
            BorderQueueDecision(ms_code="ign-1", ignored=True),
        ),
        products=products,
        border=border,
        lookup=lookup,
    )
    assert border_status("link-1", products=products, border=border) == "linked"
    assert border_status("skip-1", products=products, border=border) == "unregistered"
    assert border_status("ign-1", products=products, border=border) == "ignored"


def test_apply_border_queue_all_undecided_is_noop() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="u1", name="U", archived=False),))
    note_unregistered_codes(("u1",), products=products, border=border)
    apply_border_queue(
        (BorderQueueDecision(ms_code="u1"),),
        products=products,
        border=border,
        lookup=lookup,
    )
    assert border_status("u1", products=products, border=border) == "unregistered"


def test_apply_border_queue_rejects_ignore_with_product_id() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="u1", name="U", archived=False),))
    note_unregistered_codes(("u1",), products=products, border=border)
    ingredient = create_domain_product(
        "MilkDom",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    with pytest.raises(DomainProductRejected, match="Игнорировать"):
        apply_border_queue(
            (
                BorderQueueDecision(
                    ms_code="u1",
                    domain_product_id=ingredient.domain_product_id,
                    ignored=True,
                ),
            ),
            products=products,
            border=border,
            lookup=lookup,
        )
    assert border_status("u1", products=products, border=border) == "unregistered"


def test_apply_border_queue_rejects_non_ingredient_without_writes() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="bad", name="B", archived=False),
            CatalogProduct(code="ok", name="O", archived=False),
        )
    )
    note_unregistered_codes(("bad", "ok"), products=products, border=border)
    mm = create_domain_product(
        "MM",
        store=products,
        lookup=lookup,
        kind="micromarket",
    )
    with pytest.raises(DomainProductRejected, match="ингредиент"):
        apply_border_queue(
            (
                BorderQueueDecision(ms_code="bad", domain_product_id=mm.domain_product_id),
                BorderQueueDecision(ms_code="ok", ignored=True),
            ),
            products=products,
            border=border,
            lookup=lookup,
        )
    assert border_status("ok", products=products, border=border) == "unregistered"
    assert border_status("bad", products=products, border=border) == "unregistered"


def test_apply_border_queue_rejects_card_taken_without_writes() -> None:
    products = FakeDomainProductStore()
    border = MemoryBorderRegistrationStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="taken", name="T", archived=False),
            CatalogProduct(code="ok", name="O", archived=False),
        )
    )
    note_unregistered_codes(("taken", "ok"), products=products, border=border)
    holder = create_domain_product(
        "Holder",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    add_domain_product_link(holder.domain_product_id, "taken", store=products, lookup=lookup)
    other = create_domain_product(
        "Other",
        store=products,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    with pytest.raises(DomainProductRejected, match=CARD_TAKEN_TEXT):
        apply_border_queue(
            (
                BorderQueueDecision(ms_code="ok", ignored=True),
                BorderQueueDecision(
                    ms_code="taken",
                    domain_product_id=other.domain_product_id,
                ),
            ),
            products=products,
            border=border,
            lookup=lookup,
        )
    assert border_status("ok", products=products, border=border) == "unregistered"
    assert border_status("taken", products=products, border=border) == "linked"
