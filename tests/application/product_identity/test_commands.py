from __future__ import annotations

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.commands import (
    create_domain_product,
    hide_domain_product,
    link_domain_product,
    rename_domain_product,
)
from src.application.product_identity.models import CatalogProduct, DomainProductRejected
from src.application.product_identity.number import canonical_domain_number


def test_canonical_number_folds_d_and_keeps_leading_zeros() -> None:
    assert canonical_domain_number("  D-0100 ") == "d-0100"
    assert canonical_domain_number("d-100") == "d-100"
    assert canonical_domain_number("d-0100") != canonical_domain_number("d-100")
    assert canonical_domain_number("2311") is None
    assert canonical_domain_number("d-") is None
    assert canonical_domain_number("dd-1") is None


def test_create_assigns_d_1_without_catalog_card() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    created = create_domain_product("  Молоко ", store=store, lookup=lookup)
    assert created.number == "d-1"
    assert created.name == "Молоко"
    assert created.catalog_code is None
    assert created.hidden is False
    assert store.writes == 1


def test_create_rejects_empty_name() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    with pytest.raises(DomainProductRejected, match="Название не может быть пустым."):
        create_domain_product("   ", store=store, lookup=lookup)
    assert store.writes == 0


def test_create_skips_number_that_collides_with_catalog() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="D-1", name="Чужой", archived=False),))
    created = create_domain_product("Свой", store=store, lookup=lookup)
    assert created.number == "d-2"


def test_create_retries_after_number_conflict() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    store.fail_number_once = "d-1"
    created = create_domain_product("Свой", store=store, lookup=lookup)
    assert created.number == "d-2"
    assert store.writes == 1


def test_second_link_rejected_including_hidden_holder() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    holder = create_domain_product("Первый", store=store, lookup=lookup)
    link_domain_product(holder.domain_product_id, "2311", store=store, lookup=lookup)
    hide_domain_product(holder.domain_product_id, store=store)
    other = create_domain_product("Второй", store=store, lookup=lookup)
    with pytest.raises(DomainProductRejected, match="Карточка уже занята другим товаром."):
        link_domain_product(other.domain_product_id, "2311", store=store, lookup=lookup)


def test_link_rejects_empty_code() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    created = create_domain_product("Товар", store=store, lookup=lookup)
    with pytest.raises(DomainProductRejected, match="Кода нет в снимке."):
        link_domain_product(created.domain_product_id, "  ", store=store, lookup=lookup)


def test_hide_repeat_does_not_write_again() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    created = create_domain_product("Товар", store=store, lookup=lookup)
    hide_domain_product(created.domain_product_id, store=store)
    writes = store.writes
    hide_domain_product(created.domain_product_id, store=store)
    assert store.writes == writes


def test_repeat_link_same_code_does_not_write() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    created = create_domain_product("Товар", store=store, lookup=lookup)
    link_domain_product(created.domain_product_id, "2311", store=store, lookup=lookup)
    writes = store.writes
    again = link_domain_product(created.domain_product_id, "2311", store=store, lookup=lookup)
    assert again.catalog_code == "2311"
    assert store.writes == writes


def test_link_rejects_code_absent_from_snapshot() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    created = create_domain_product("Товар", store=store, lookup=lookup)
    with pytest.raises(DomainProductRejected, match="Кода нет в снимке."):
        link_domain_product(created.domain_product_id, "9999", store=store, lookup=lookup)
    assert store.writes == 1


def test_link_archived_card() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2400", name="Архив", archived=True),))
    created = create_domain_product("Товар", store=store, lookup=lookup)
    linked = link_domain_product(created.domain_product_id, "2400", store=store, lookup=lookup)
    assert linked.catalog_code == "2400"


def test_rename_rejects_empty_name() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    created = create_domain_product("Товар", store=store, lookup=lookup)
    with pytest.raises(DomainProductRejected, match="Название не может быть пустым."):
        rename_domain_product(created.domain_product_id, "   ", store=store)
    assert store.writes == 1


def test_rename_same_name_does_not_write() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    created = create_domain_product("Товар", store=store, lookup=lookup)
    writes = store.writes
    renamed = rename_domain_product(created.domain_product_id, " Товар ", store=store)
    assert renamed.name == "Товар"
    assert store.writes == writes
