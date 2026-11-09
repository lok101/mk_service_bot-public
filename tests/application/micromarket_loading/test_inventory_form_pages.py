from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.micromarket_loading.inventory_form_pages import (
    OFF_PLANOGRAM_PAGE_TITLE,
    build_micromarket_inventory_form_pages,
    flatten_inventory_form_page_codes,
)
from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
)
from src.application.product_identity import create_domain_product

_NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _line(
    *,
    product_id: str,
    kit_group_id: int | None,
    sort_order: int,
    active: bool = True,
    pending_exit: bool = False,
) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code="",
        target_qty=1,
        price_rub=Decimal("10"),
        active=active,
        sort_order=sort_order,
        kit_group_id=kit_group_id,
        domain_product_id=product_id,
        pending_exit=pending_exit,
    )


def test_pages_two_shelves_plus_off_planogram() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    shelf_a_beta = create_domain_product("Бета", store=store, lookup=lookup)
    shelf_a_alpha = create_domain_product("Альфа", store=store, lookup=lookup)
    shelf_b = create_domain_product("Гамма", store=store, lookup=lookup)
    off = create_domain_product("Остаток", store=store, lookup=lookup)
    planogram = MicromarketPlanogram(
        machine_code="701",
        lines=(
            _line(product_id=shelf_a_beta.domain_product_id, kit_group_id=10, sort_order=0),
            _line(product_id=shelf_a_alpha.domain_product_id, kit_group_id=10, sort_order=1),
            _line(product_id=shelf_b.domain_product_id, kit_group_id=20, sort_order=2),
        ),
        updated_at=_NOW,
        shelves=(
            MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
            MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
        ),
    )
    pages = build_micromarket_inventory_form_pages(
        planogram=planogram,
        stock_qty={off.number: Decimal("1")},
        products=store,
        kit_group_names={10: "Холод", 20: "Снеки"},
    )
    assert len(pages) == 3
    assert pages[0].kit_group_id == 10
    assert pages[0].title == "Холод"
    assert pages[0].product_codes == (shelf_a_alpha.number, shelf_a_beta.number)
    assert pages[1].kit_group_id == 20
    assert pages[1].title == "Снеки"
    assert pages[1].product_codes == (shelf_b.number,)
    assert pages[2].kit_group_id is None
    assert pages[2].title == OFF_PLANOGRAM_PAGE_TITLE
    assert pages[2].product_codes == (off.number,)
    assert flatten_inventory_form_page_codes(pages) == (
        shelf_a_alpha.number,
        shelf_a_beta.number,
        shelf_b.number,
        off.number,
    )


def test_pages_synthesize_shelves_when_none() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    first = create_domain_product("А", store=store, lookup=lookup)
    second = create_domain_product("Б", store=store, lookup=lookup)
    planogram = MicromarketPlanogram(
        machine_code="701",
        lines=(
            _line(product_id=second.domain_product_id, kit_group_id=20, sort_order=0),
            _line(product_id=first.domain_product_id, kit_group_id=10, sort_order=1),
        ),
        updated_at=_NOW,
        shelves=None,
    )
    pages = build_micromarket_inventory_form_pages(
        planogram=planogram,
        stock_qty={},
        products=store,
    )
    assert [page.kit_group_id for page in pages] == [20, 10]
    assert pages[0].title == "группа 20"
    assert pages[1].title == "группа 10"


def test_pages_pending_exit_after_active_on_shelf() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    active = create_domain_product("Яблоко", store=store, lookup=lookup)
    exiting = create_domain_product("Абрикос", store=store, lookup=lookup)
    planogram = MicromarketPlanogram(
        machine_code="701",
        lines=(
            _line(
                product_id=exiting.domain_product_id,
                kit_group_id=10,
                sort_order=0,
                active=False,
                pending_exit=True,
            ),
            _line(product_id=active.domain_product_id, kit_group_id=10, sort_order=1),
        ),
        updated_at=_NOW,
        shelves=(MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),),
    )
    pages = build_micromarket_inventory_form_pages(
        planogram=planogram,
        stock_qty={},
        products=store,
    )
    assert len(pages) == 1
    assert pages[0].product_codes == (active.number, exiting.number)


def test_pages_skip_empty_shelf() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    only = create_domain_product("Товар", store=store, lookup=lookup)
    planogram = MicromarketPlanogram(
        machine_code="701",
        lines=(_line(product_id=only.domain_product_id, kit_group_id=10, sort_order=0),),
        updated_at=_NOW,
        shelves=(
            MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
            MicromarketPlanogramShelf(kit_group_id=99, sort_order=1),
        ),
    )
    pages = build_micromarket_inventory_form_pages(
        planogram=planogram,
        stock_qty={},
        products=store,
    )
    assert [page.kit_group_id for page in pages] == [10]


def test_pages_stock_only_off_planogram() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())
    stock_only = create_domain_product("Вне", store=store, lookup=lookup)
    pages = build_micromarket_inventory_form_pages(
        planogram=None,
        stock_qty={stock_only.number: Decimal("2")},
        products=store,
    )
    assert len(pages) == 1
    assert pages[0].kit_group_id is None
    assert pages[0].title == OFF_PLANOGRAM_PAGE_TITLE
    assert pages[0].product_codes == (stock_only.number,)


def test_pages_empty_sku_set() -> None:
    pages = build_micromarket_inventory_form_pages(
        planogram=None,
        stock_qty={},
        products=FakeDomainProductStore(),
    )
    assert pages == ()
