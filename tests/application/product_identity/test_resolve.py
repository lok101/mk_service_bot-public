from __future__ import annotations

from dataclasses import replace

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.commands import (
    create_domain_product,
    hide_domain_product,
    link_domain_product,
)
from src.application.product_identity.models import CatalogProduct, DomainProduct
from src.application.product_identity.resolve import (
    KitShopRecognized,
    ResolveHold,
    ResolveLegacy,
    ResolveRecognized,
    resolve_kit_shop_sale_code,
    resolve_sale_code,
)


def _linked(
    code: str,
    *,
    archived: bool,
) -> tuple[FakeDomainProductStore, FakeCatalogLookup, DomainProduct]:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code=code, name="Карточка", archived=archived),))
    product = create_domain_product("Товар", store=store, lookup=lookup)
    linked = link_domain_product(product.domain_product_id, code, store=store, lookup=lookup)
    return store, lookup, linked


def test_hidden_product_still_resolves_by_number() -> None:
    store, lookup, product = _linked("2311", archived=False)
    hide_domain_product(product.domain_product_id, store=store)
    resolved = resolve_sale_code("D-1", store=store, lookup=lookup)
    assert isinstance(resolved, ResolveRecognized)
    assert resolved.domain_product_id == product.domain_product_id
    assert resolved.catalog_code == "2311"


def test_relink_leaves_previous_resolve_value() -> None:
    store, lookup, product = _linked("2311", archived=False)
    lookup.cards["2312"] = CatalogProduct(code="2312", name="Новая", archived=False)
    first = resolve_sale_code("2311", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2312", store=store, lookup=lookup)
    assert isinstance(first, ResolveRecognized)
    assert first.catalog_code == "2311"
    second = resolve_sale_code("2312", store=store, lookup=lookup)
    assert isinstance(second, ResolveRecognized)
    assert second.domain_product_id == product.domain_product_id


def test_resolve_catalog_code_recognizes_same_product() -> None:
    store, lookup, product = _linked("2311", archived=False)
    by_number = resolve_sale_code("d-1", store=store, lookup=lookup)
    by_code = resolve_sale_code("2311", store=store, lookup=lookup)
    assert isinstance(by_number, ResolveRecognized)
    assert isinstance(by_code, ResolveRecognized)
    assert by_number.domain_product_id == by_code.domain_product_id == product.domain_product_id
    assert by_code.catalog_code == "2311"


def test_resolve_plain_code_is_legacy() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    resolved = resolve_sale_code("2311", store=store, lookup=lookup)
    assert isinstance(resolved, ResolveLegacy)
    assert resolved.code == "2311"


def test_resolve_unknown_number_holds() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    resolved = resolve_sale_code("d-1001", store=store, lookup=lookup)
    assert isinstance(resolved, ResolveHold)
    assert resolved.kind == "hold_unknown_number"


def test_resolve_number_present_in_catalog_is_legacy() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="d-1001", name="Карточка", archived=False),))
    resolved = resolve_sale_code("d-1001", store=store, lookup=lookup)
    assert isinstance(resolved, ResolveLegacy)
    assert resolved.code == "d-1001"


def test_resolve_unlinked_broken_and_archived_hold() -> None:
    bare_store = FakeDomainProductStore()
    bare_lookup = FakeCatalogLookup(())
    bare = create_domain_product("Пустой", store=bare_store, lookup=bare_lookup)
    unlinked = resolve_sale_code(bare.number, store=bare_store, lookup=bare_lookup)
    assert isinstance(unlinked, ResolveHold)
    assert unlinked.kind == "hold_unlinked"

    broken_store, broken_lookup, broken = _linked("2311", archived=False)
    broken_lookup.cards.pop("2311")
    broken_result = resolve_sale_code(broken.number, store=broken_store, lookup=broken_lookup)
    assert isinstance(broken_result, ResolveHold)
    assert broken_result.kind == "hold_broken"

    archived_store, archived_lookup, archived = _linked("2400", archived=True)
    archived_result = resolve_sale_code(
        archived.number,
        store=archived_store,
        lookup=archived_lookup,
    )
    assert isinstance(archived_result, ResolveHold)
    assert archived_result.kind == "hold_archived"


def test_kit_shop_number_without_catalog_code_returns_number() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    product = create_domain_product("Молоко", store=store, lookup=lookup)
    resolved = resolve_kit_shop_sale_code(product.number, store=store, lookup=lookup)
    assert isinstance(resolved, KitShopRecognized)
    assert resolved.domain_product_id == product.domain_product_id
    assert resolved.number == product.number
    assert resolved.alias_from is None


def test_kit_shop_catalog_code_alias_returns_same_number() -> None:
    store, lookup, product = _linked("2311", archived=False)
    by_number = resolve_kit_shop_sale_code(product.number, store=store, lookup=lookup)
    by_code = resolve_kit_shop_sale_code("2311", store=store, lookup=lookup)
    assert isinstance(by_number, KitShopRecognized)
    assert isinstance(by_code, KitShopRecognized)
    assert by_number.number == by_code.number == product.number
    assert by_code.alias_from == "2311"
    assert by_number.alias_from is None


def test_kit_shop_unknown_number_holds() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    resolved = resolve_kit_shop_sale_code("d-1001", store=store, lookup=lookup)
    assert isinstance(resolved, ResolveHold)
    assert resolved.kind == "hold_unknown_number"


def test_kit_shop_empty_broken_archived_catalog_still_recognizes_number() -> None:
    bare_store = FakeDomainProductStore()
    bare_lookup = FakeCatalogLookup(())
    bare = create_domain_product("Пустой", store=bare_store, lookup=bare_lookup)
    bare_result = resolve_kit_shop_sale_code(bare.number, store=bare_store, lookup=bare_lookup)
    assert isinstance(bare_result, KitShopRecognized)
    assert bare_result.number == bare.number

    broken_store, broken_lookup, broken = _linked("2311", archived=False)
    broken_lookup.cards.pop("2311")
    broken_result = resolve_kit_shop_sale_code(
        broken.number,
        store=broken_store,
        lookup=broken_lookup,
    )
    assert isinstance(broken_result, KitShopRecognized)
    assert broken_result.number == broken.number

    archived_store, archived_lookup, archived = _linked("2400", archived=True)
    archived_result = resolve_kit_shop_sale_code(
        archived.number,
        store=archived_store,
        lookup=archived_lookup,
    )
    assert isinstance(archived_result, KitShopRecognized)
    assert archived_result.number == archived.number


def test_coffee_drink_kit_code_without_catalog_card_stays_legacy() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    drink = create_domain_product(
        "Моккачино 350мл",
        store=store,
        lookup=lookup,
        kind="coffee_drink",
    )
    saved = store.get(drink.domain_product_id)
    assert saved is not None
    store.save(replace(saved, legacy_ms_code="305"))

    resolved = resolve_sale_code("305", store=store, lookup=lookup)

    assert isinstance(resolved, ResolveLegacy)
    assert resolved.code == "305"


def test_vending_unlinked_still_holds_while_kit_shop_recognizes() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    product = create_domain_product("Пустой", store=store, lookup=lookup)
    vending = resolve_sale_code(product.number, store=store, lookup=lookup)
    kit = resolve_kit_shop_sale_code(product.number, store=store, lookup=lookup)
    assert isinstance(vending, ResolveHold)
    assert vending.kind == "hold_unlinked"
    assert isinstance(kit, KitShopRecognized)
    assert kit.number == product.number
