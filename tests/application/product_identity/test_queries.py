from __future__ import annotations

from decimal import Decimal

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.product_identity.commands import (
    create_domain_product,
    hide_domain_product,
    link_domain_product,
)
from src.application.product_identity.models import CatalogProduct
from src.application.product_identity.queries import (
    HOLD_REASON,
    catalog_card_window,
    hold_alert_text,
    list_domain_products,
    search_catalog_cards,
)
from src.domain.product_catalog import ProductUnit


def test_catalog_card_window_puts_exact_code_first() -> None:
    cards = (
        CatalogProduct(code="b", name="Бета", archived=False),
        CatalogProduct(code="a", name="Альфа", archived=False),
        CatalogProduct(code="ab", name="Аб", archived=False),
    )
    window = catalog_card_window("a", cards=cards)
    assert [hit.code for hit in window.hits] == ["a", "ab"]
    assert window.truncated is False


def test_catalog_card_window_matches_name_substring() -> None:
    cards = (
        CatalogProduct(code="2311", name="Молоко", archived=False),
        CatalogProduct(code="2400", name="Чай", archived=False),
    )
    window = catalog_card_window("мол", cards=cards)
    assert [hit.code for hit in window.hits] == ["2311"]
    assert window.hits[0].name == "Молоко"


def test_catalog_card_window_empty_query_is_empty() -> None:
    cards = (CatalogProduct(code="2311", name="Молоко", archived=False),)
    blank = catalog_card_window("   ", cards=cards)
    empty = catalog_card_window("", cards=cards)
    assert blank.hits == ()
    assert blank.truncated is False
    assert empty.hits == ()
    assert empty.truncated is False


def test_catalog_card_window_truncates_after_eight() -> None:
    cards = tuple(
        CatalogProduct(code=f"c{index}", name=f"Молоко {index}", archived=False)
        for index in range(9)
    )
    window = catalog_card_window("молоко", cards=cards)
    assert len(window.hits) == 8
    assert [hit.code for hit in window.hits] == [f"c{index}" for index in range(8)]
    assert window.truncated is True


def test_catalog_card_window_includes_archived() -> None:
    cards = (CatalogProduct(code="9001", name="Старое молоко", archived=True),)
    window = catalog_card_window("стар", cards=cards)
    assert window.hits[0].archived is True
    assert window.hits[0].code == "9001"


def test_catalog_card_window_exact_code_ignores_case() -> None:
    cards = (
        CatalogProduct(code="zz", name="Чай", archived=False),
        CatalogProduct(code="Ab", name="Молоко", archived=False),
    )
    window = catalog_card_window(" ab ", cards=cards)
    assert [hit.code for hit in window.hits] == ["Ab"]
    assert window.truncated is False


def test_list_excludes_coffee_kinds_from_retail_catalog() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    mm = create_domain_product("Молоко MM", store=store, lookup=lookup)
    create_domain_product(
        "Зерно",
        store=store,
        lookup=lookup,
        kind="coffee_ingredient",
        unit=ProductUnit.GRAM,
        pack_size=Decimal("1000"),
    )
    create_domain_product(
        "Латте",
        store=store,
        lookup=lookup,
        kind="coffee_drink",
    )
    rows = list_domain_products("all", store=store, lookup=lookup)
    assert [row.domain_product_id for row in rows] == [mm.domain_product_id]


def test_list_excludes_hidden_and_filters_unlinked() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    visible = create_domain_product("Виден", store=store, lookup=lookup)
    hidden = create_domain_product("Скрыт", store=store, lookup=lookup)
    hide_domain_product(hidden.domain_product_id, store=store)
    rows = list_domain_products("unlinked", store=store, lookup=lookup)
    assert [row.domain_product_id for row in rows] == [visible.domain_product_id]
    assert rows[0].state == "нет связи"


def test_search_catalog_cards_caps_at_50() -> None:
    cards = tuple(
        CatalogProduct(code=str(index), name=f"n{index}", archived=False) for index in range(60)
    )
    found = search_catalog_cards("", lookup=FakeCatalogLookup(cards, search_limit=None))
    assert len(found) == 50


def test_list_linked_keeps_archive_and_broken() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(
        (
            CatalogProduct(code="2311", name="Молоко", archived=False),
            CatalogProduct(code="2400", name="Старое", archived=True),
            CatalogProduct(code="9999", name="Была", archived=False),
        )
    )
    linked = create_domain_product("Живой", store=store, lookup=lookup)
    link_domain_product(linked.domain_product_id, "2311", store=store, lookup=lookup)
    archived = create_domain_product("Архив", store=store, lookup=lookup)
    link_domain_product(archived.domain_product_id, "2400", store=store, lookup=lookup)
    broken = create_domain_product("Обрыв", store=store, lookup=lookup)
    link_domain_product(broken.domain_product_id, "9999", store=store, lookup=lookup)
    lookup.cards.pop("9999")
    hidden = create_domain_product("Скрыт", store=store, lookup=lookup)
    hide_domain_product(hidden.domain_product_id, store=store)

    rows = list_domain_products("linked", store=store, lookup=lookup)
    by_id = {row.domain_product_id: row for row in rows}
    assert set(by_id) == {
        linked.domain_product_id,
        archived.domain_product_id,
        broken.domain_product_id,
    }
    assert by_id[linked.domain_product_id].state == "связана"
    assert by_id[linked.domain_product_id].catalog_name == "Молоко"
    assert by_id[archived.domain_product_id].state == "архив"
    assert by_id[broken.domain_product_id].state == "порвана"

    visible = list_domain_products("all", store=store, lookup=lookup)
    assert hidden.domain_product_id not in {row.domain_product_id for row in visible}
    assert len(visible) == 3


def test_hold_alert_text_returns_four_reasons() -> None:
    assert HOLD_REASON["hold_unlinked"] == "domain_product_unlinked"
    assert HOLD_REASON["hold_broken"] == "domain_product_link_broken"
    assert HOLD_REASON["hold_archived"] == "domain_product_catalog_archived"
    assert HOLD_REASON["hold_unknown_number"] == "unknown_domain_number"
    assert hold_alert_text("domain_product_unlinked") == (
        "Товар не связан с карточкой каталога, продажа не записана."
    )
    assert hold_alert_text("domain_product_link_broken") == (
        "Связь с карточкой каталога порвана, продажа не записана."
    )
    assert hold_alert_text("domain_product_catalog_archived") == (
        "Карточка каталога в архиве, продажа не записана."
    )
    assert hold_alert_text("unknown_domain_number") == (
        "На карточке код доменного номера, а товара с таким номером нет."
    )
    assert hold_alert_text("other") is None
