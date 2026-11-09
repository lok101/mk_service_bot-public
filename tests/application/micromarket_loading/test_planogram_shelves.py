from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.micromarket_loading import (
    GetMicromarketLoadingPreview,
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    SaveMicromarketPlanogram,
    ShopListPublishStatus,
    planogram_line_sort_key,
)
from src.application.product_identity import DomainProduct
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
)

_FROZEN = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _line(
    code: str,
    *,
    kit_group_id: int | None,
    sort_order: int = 0,
    pending_exit: bool = False,
    domain_product_id: str | None = None,
    active: bool = True,
    price: str = "10",
) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code=code,
        target_qty=1,
        price_rub=Decimal(price),
        active=active,
        sort_order=sort_order,
        kit_group_id=kit_group_id,
        domain_product_id=domain_product_id,
        pending_exit=pending_exit,
    )


def test_planogram_shelves_default_none() -> None:
    doc = MicromarketPlanogram(
        machine_code="701",
        lines=(),
        updated_at=_FROZEN,
    )
    assert doc.shelves is None


def test_planogram_line_sort_key_uses_domain_name_and_normalizes_yo() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="p1",
            number="n1",
            name="Ёлка",
            catalog_code="2311",
            hidden=False,
        )
    )
    line = MicromarketPlanogramLine(
        product_code="",
        target_qty=1,
        price_rub=Decimal("10"),
        active=True,
        sort_order=0,
        kit_group_id=1,
        domain_product_id="p1",
    )
    key = planogram_line_sort_key(line, products=products)
    assert key[0] == "елка"
    assert key[1] == "p1"


def test_planogram_line_sort_key_missing_domain_product() -> None:
    line = MicromarketPlanogramLine(
        product_code="",
        target_qty=1,
        price_rub=Decimal("10"),
        active=True,
        sort_order=0,
        kit_group_id=1,
        domain_product_id="missing",
    )
    key = planogram_line_sort_key(line, products=FakeDomainProductStore())
    assert key[0] == "товар не найден"


def test_planogram_line_sort_key_legacy_code_uses_catalog_names() -> None:
    line = MicromarketPlanogramLine(
        product_code="2311",
        target_qty=1,
        price_rub=Decimal("10"),
        active=True,
        sort_order=0,
        kit_group_id=1,
    )
    key = planogram_line_sort_key(line, catalog_names={"2311": "Вода"})
    assert key[0] == "вода"
    assert key[2] == "2311"


def test_planogram_line_sort_key_stable_on_equal_names() -> None:
    products = FakeDomainProductStore()
    for pid, name in (("a", "Сок"), ("b", "Сок")):
        products.insert(
            DomainProduct(
                domain_product_id=pid,
                number=pid,
                name=name,
                catalog_code=pid,
                hidden=False,
            )
        )
    left = MicromarketPlanogramLine(
        product_code="",
        target_qty=1,
        price_rub=Decimal("1"),
        active=True,
        sort_order=0,
        kit_group_id=1,
        domain_product_id="b",
    )
    right = MicromarketPlanogramLine(
        product_code="",
        target_qty=1,
        price_rub=Decimal("1"),
        active=True,
        sort_order=1,
        kit_group_id=1,
        domain_product_id="a",
    )
    assert planogram_line_sort_key(left, products=products) > planogram_line_sort_key(
        right, products=products
    )


def test_save_with_shelves_orders_by_shelf_then_pending_exit_then_alphabet() -> None:
    # happy: полки по порядку; внутри полки обычные (alpha) затем pending_exit (alpha)
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="p-yo",
            number="n-yo",
            name="Ёлка",
            catalog_code="2311",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="p-water",
            number="n-water",
            name="Вода",
            catalog_code="2312",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="p-exit",
            number="n-exit",
            name="Апельсин",
            catalog_code="2313",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="p-exit-z",
            number="n-exit-z",
            name="Яблоко",
            catalog_code="2314",
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    doc = SaveMicromarketPlanogram(
        store=store,
        catalog_codes=set(),
        products=products,
    ).execute(
        machine_code="701",
        shelves=[
            MicromarketPlanogramShelf(kit_group_id=10, sort_order=99),
            MicromarketPlanogramShelf(kit_group_id=20, sort_order=0),
        ],
        lines=[
            _line("", kit_group_id=20, domain_product_id="p-yo", sort_order=99),
            _line("", kit_group_id=10, domain_product_id="p-water", sort_order=50),
            _line(
                "",
                kit_group_id=10,
                domain_product_id="p-exit",
                pending_exit=True,
                sort_order=0,
            ),
            _line(
                "",
                kit_group_id=10,
                domain_product_id="p-exit-z",
                pending_exit=True,
                sort_order=1,
            ),
        ],
    )
    assert doc.shelves == (
        MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
        MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
    )
    # shelf 10: Вода (normal) then Апельсин/Яблоко (pending alpha); shelf 20: Ёлка
    assert [line.domain_product_id for line in doc.lines] == [
        "p-water",
        "p-exit",
        "p-exit-z",
        "p-yo",
    ]
    assert [line.sort_order for line in doc.lines] == [0, 1, 2, 3]
    assert [line.kit_group_id for line in doc.lines] == [10, 10, 10, 20]
    assert [line.pending_exit for line in doc.lines] == [False, True, True, False]


def test_save_drops_shelf_without_product_line() -> None:
    store = InMemoryMicromarketPlanogramStore()
    doc = SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        machine_code="701",
        shelves=[
            MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
            MicromarketPlanogramShelf(kit_group_id=40, sort_order=1),
        ],
        lines=[_line("2311", kit_group_id=10)],
    )
    assert doc.shelves == (MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),)
    assert [line.product_code for line in doc.lines] == ["2311"]


def test_save_requires_shelves_argument() -> None:
    # кусок 03: ветка execute без shelves снята
    store = InMemoryMicromarketPlanogramStore()
    with pytest.raises(TypeError, match="shelves"):
        SaveMicromarketPlanogram(store=store, catalog_codes={"2311", "2312"}).execute(
            machine_code="701",
            lines=[
                _line("2311", kit_group_id=1, pending_exit=True, sort_order=0),
                _line("2312", kit_group_id=1, pending_exit=False, sort_order=1),
            ],
        )


def test_save_appends_line_category_missing_from_shelf_fields() -> None:
    store = InMemoryMicromarketPlanogramStore()
    doc = SaveMicromarketPlanogram(store=store, catalog_codes={"2311", "2312"}).execute(
        machine_code="701",
        shelves=[MicromarketPlanogramShelf(kit_group_id=10, sort_order=5)],
        lines=[
            _line("2312", kit_group_id=99),
            _line("2311", kit_group_id=10),
        ],
    )
    assert doc.shelves == (
        MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
        MicromarketPlanogramShelf(kit_group_id=99, sort_order=1),
    )
    assert [line.kit_group_id for line in doc.lines] == [10, 99]


def test_save_rejects_active_line_without_category() -> None:
    store = InMemoryMicromarketPlanogramStore()
    with pytest.raises(ValueError, match="kit_group_id required"):
        SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
            machine_code="701",
            shelves=[MicromarketPlanogramShelf(kit_group_id=10, sort_order=0)],
            lines=[_line("2311", kit_group_id=None)],
        )


def test_save_rejects_duplicate_shelf_group() -> None:
    store = InMemoryMicromarketPlanogramStore()
    with pytest.raises(ValueError, match="Две полки с одной группой Kit"):
        SaveMicromarketPlanogram(store=store, catalog_codes=set()).execute(
            machine_code="701",
            shelves=[
                MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
                MicromarketPlanogramShelf(kit_group_id=10, sort_order=1),
            ],
            lines=[],
        )


def test_save_rejects_non_positive_shelf_id() -> None:
    store = InMemoryMicromarketPlanogramStore()
    with pytest.raises(ValueError, match="Некорректная полка"):
        SaveMicromarketPlanogram(store=store, catalog_codes=set()).execute(
            machine_code="701",
            shelves=[MicromarketPlanogramShelf(kit_group_id=0, sort_order=0)],
            lines=[],
        )


def _publish(store: InMemoryMicromarketPlanogramStore) -> None:
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311", "2312"}).execute(
        machine_code="701",
        shelves=[
            MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
            MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
        ],
        lines=[
            _line("2311", kit_group_id=10),
            _line("2312", kit_group_id=20),
        ],
    )
    doc = store.get("701")
    assert doc is not None
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=doc.lines,
            updated_at=doc.updated_at,
            shelves=doc.shelves,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id="pub-1",
        )
    )


def test_reorder_shelves_keeps_published_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    _publish(store)
    doc = SaveMicromarketPlanogram(store=store, catalog_codes={"2311", "2312"}).execute(
        machine_code="701",
        shelves=[
            MicromarketPlanogramShelf(kit_group_id=20, sort_order=0),
            MicromarketPlanogramShelf(kit_group_id=10, sort_order=1),
        ],
        lines=[
            _line("2311", kit_group_id=10),
            _line("2312", kit_group_id=20),
        ],
    )
    assert doc.shop_list_status is ShopListPublishStatus.PUBLISHED
    assert doc.shop_list_publication_id == "pub-1"


def test_move_line_to_other_shelf_clears_published_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    _publish(store)
    doc = SaveMicromarketPlanogram(store=store, catalog_codes={"2311", "2312"}).execute(
        machine_code="701",
        shelves=[
            MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),
            MicromarketPlanogramShelf(kit_group_id=20, sort_order=1),
        ],
        lines=[
            _line("2311", kit_group_id=20),
            _line("2312", kit_group_id=20),
        ],
    )
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert doc.shop_list_publication_id == ""


class _Publisher:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def _seed_factual(
    stock_store: InMemoryMicromarketDeviceStockStore,
    quantities: dict[str, Decimal],
) -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities=quantities,
        inventory_id="inv-1",
        partial=True,
    )
    stock_store.save(stock)


def test_save_with_shelves_clears_zero_pending_exit_and_renumbers() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="gone",
            number="n-gone",
            name="Уйти",
            catalog_code="2311",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="keep",
            number="n-keep",
            name="Остаться",
            catalog_code="2312",
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    publisher = _Publisher()
    _seed_factual(stock_store, {"n-gone": Decimal("0")})
    doc = SaveMicromarketPlanogram(
        store=store,
        catalog_codes=set(),
        products=products,
        stock_store=stock_store,
        publisher=publisher,
    ).execute(
        machine_code="701",
        shelves=[MicromarketPlanogramShelf(kit_group_id=10, sort_order=0)],
        lines=[
            _line("", kit_group_id=10, domain_product_id="gone", pending_exit=True),
            _line("", kit_group_id=10, domain_product_id="keep"),
        ],
    )
    assert [line.domain_product_id for line in doc.lines] == ["keep"]
    assert doc.lines[0].sort_order == 0
    assert doc.shelves == (MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),)
    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], MicromarketShopListPublishRequested)


def test_loading_preview_follows_saved_sort_order_after_shelves() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="b",
            number="nb",
            name="Б",
            catalog_code="2312",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="a",
            number="na",
            name="А",
            catalog_code="2311",
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    SaveMicromarketPlanogram(store=store, catalog_codes=set(), products=products).execute(
        machine_code="701",
        shelves=[
            MicromarketPlanogramShelf(kit_group_id=20, sort_order=0),
            MicromarketPlanogramShelf(kit_group_id=10, sort_order=1),
        ],
        lines=[
            _line("", kit_group_id=10, domain_product_id="a"),
            _line("", kit_group_id=20, domain_product_id="b"),
        ],
    )
    preview = GetMicromarketLoadingPreview(
        planogram_store=store,
        stock_store=InMemoryMicromarketDeviceStockStore(),
        catalog_names={},
        products=products,
    ).execute("701")
    assert [row.product_code for row in preview.rows] == ["nb", "na"]


def test_publish_job_preserves_shelves_on_status_copy() -> None:
    from src.application.micromarket_loading.publish_job import (
        mark_shop_list_publication_failed,
    )

    store = InMemoryMicromarketPlanogramStore()
    shelves = (MicromarketPlanogramShelf(kit_group_id=10, sort_order=0),)
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_line("2311", kit_group_id=10),),
            updated_at=_FROZEN,
            shelves=shelves,
            shop_list_status=ShopListPublishStatus.PUBLISHING,
            shop_list_publication_id="pub-x",
        )
    )
    mark_shop_list_publication_failed(store, "pub-x", "fail", machine_code="701")
    doc = store.get("701")
    assert doc is not None
    assert doc.shelves == shelves


def test_accept_inventory_preserves_shelves_and_renumbers_after_zero() -> None:
    from src.application.micromarket_loading import AcceptMicromarketInventory
    from src.infrastructure.testing.micromarket_loading_fakes import (
        InMemoryMicromarketSalesAfter,
    )

    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="gone",
            number="n-gone",
            name="Яблоко",
            catalog_code="2311",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="keep-b",
            number="n-keep-b",
            name="Б",
            catalog_code="2312",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="keep-a",
            number="n-keep-a",
            name="А",
            catalog_code="2313",
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    shelves = (
        MicromarketPlanogramShelf(kit_group_id=20, sort_order=0),
        MicromarketPlanogramShelf(kit_group_id=10, sort_order=1),
    )
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _line(
                    "",
                    kit_group_id=10,
                    domain_product_id="gone",
                    pending_exit=True,
                    sort_order=0,
                ),
                _line("", kit_group_id=10, domain_product_id="keep-b", sort_order=1),
                _line("", kit_group_id=20, domain_product_id="keep-a", sort_order=2),
            ),
            updated_at=_FROZEN,
            shelves=shelves,
        )
    )
    AcceptMicromarketInventory(
        stock_store=InMemoryMicromarketDeviceStockStore(),
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=store,
        products=products,
    ).execute(
        mode="as_of",
        machine_code="701",
        quantities={
            "n-gone": Decimal("0"),
            "n-keep-a": Decimal("1"),
            "n-keep-b": Decimal("1"),
        },
        inventory_id="inv-shelves-zero",
        submitted_at=_FROZEN,
        as_of_from_form=_FROZEN,
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.shelves == shelves
    assert [line.domain_product_id for line in doc.lines] == ["keep-a", "keep-b"]
    assert [line.sort_order for line in doc.lines] == [0, 1]
