from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.micromarket_loading import (
    GetMicromarketPlanogram,
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    SaveMicromarketPlanogram,
    ShopListPublishStatus,
)
from src.application.micromarket_loading.shop_list_publish_journal import (
    ShopListPublishJournalStatus,
    ShopListPublishTrigger,
)
from src.application.product_identity import DomainProduct
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
    InMemoryShopListPublishJournal,
)


def _shelf(*group_ids: int) -> tuple[MicromarketPlanogramShelf, ...]:
    return tuple(
        MicromarketPlanogramShelf(kit_group_id=group_id, sort_order=index)
        for index, group_id in enumerate(group_ids)
    )


def test_save_and_get_planogram_roundtrip() -> None:
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311", "2312"},
    )
    get = GetMicromarketPlanogram(store=store)
    save.execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=5,
                price_rub=Decimal("189.00"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            ),
        ],
    )
    doc = get.execute("701")
    assert doc is not None
    assert doc.lines[0].product_code == "2311"
    assert doc.lines[0].target_qty == 5


def test_save_planogram_rejects_duplicate_product_code() -> None:
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
    )
    with pytest.raises(ValueError, match="duplicate"):
        save.execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=2,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=1,
                    kit_group_id=6348,
                ),
            ],
        )


def test_save_planogram_rejects_unknown_product_code() -> None:
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
    )
    with pytest.raises(ValueError, match="unknown"):
        save.execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                MicromarketPlanogramLine(
                    product_code="9999",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ],
        )


def test_save_planogram_rejects_negative_target_or_price() -> None:
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
    )
    with pytest.raises(ValueError):
        save.execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=-1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ],
        )


def test_save_planogram_rejects_zero_or_fractional_price() -> None:
    # happy-path priced rows still save; edge/error: price < 1 or non-integer rejected
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
    )
    save.execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=1,
                price_rub=Decimal("189"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            ),
        ],
    )
    assert store.get("701") is not None
    with pytest.raises(ValueError, match="price_rub"):
        save.execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("0"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ],
        )
    with pytest.raises(ValueError, match="price_rub"):
        save.execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("12.5"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                ),
            ],
        )


def test_save_planogram_allows_empty_lines() -> None:
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
    )
    get = GetMicromarketPlanogram(store=store)
    save.execute(machine_code="701", lines=[], shelves=())
    doc = get.execute("701")
    assert doc is not None
    assert doc.lines == ()
    assert doc.shelves == ()


def test_save_active_line_without_kit_group_id_rejected() -> None:
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
    )
    with pytest.raises(ValueError, match="2311"):
        save.execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=None,
                ),
            ],
        )
    assert store.get("701") is None


def test_save_inactive_line_without_kit_group_id() -> None:
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(store=store, catalog_codes={"2311"})
    saved = save.execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=1,
                price_rub=Decimal("10"),
                active=False,
                sort_order=0,
                kit_group_id=6348,
            ),
        ],
    )
    assert saved.lines[0].kit_group_id == 6348
    assert saved.lines[0].active is False


def _save_published(store: InMemoryMicromarketPlanogramStore) -> None:
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=5,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            ),
        ],
    )
    current = store.get("701")
    assert current is not None
    store.upsert(
        MicromarketPlanogram(
            machine_code=current.machine_code,
            lines=current.lines,
            updated_at=current.updated_at,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_error="старая",
            shop_list_publication_id="pub-1",
        ),
    )


def test_save_price_change_resets_published_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    _save_published(store)
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=5,
                price_rub=Decimal("11"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            ),
        ],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert doc.shop_list_error == ""
    assert doc.shop_list_publication_id == ""


def test_save_group_change_resets_published_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    _save_published(store)
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        shelves=_shelf(6349),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=5,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6349,
            ),
        ],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert doc.shop_list_publication_id == ""


def test_save_active_flag_resets_published_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    _save_published(store)
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=5,
                price_rub=Decimal("10"),
                active=False,
                sort_order=0,
                kit_group_id=6348,
            ),
        ],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert doc.shop_list_publication_id == ""


def test_save_line_set_change_resets_published_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    _save_published(store)
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311", "2312"}).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=5,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            ),
            MicromarketPlanogramLine(
                product_code="2312",
                target_qty=1,
                price_rub=Decimal("20"),
                active=True,
                sort_order=1,
                kit_group_id=6348,
            ),
        ],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert doc.shop_list_publication_id == ""


def test_save_target_qty_keeps_published_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    _save_published(store)
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=9,
                price_rub=Decimal("10"),
                active=True,
                sort_order=3,
                kit_group_id=6348,
            ),
        ],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.PUBLISHED
    assert doc.shop_list_publication_id == "pub-1"


def test_save_planogram_accepts_domain_product_without_catalog_code() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="d-1",
            name="Кефир",
            catalog_code=None,
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    SaveMicromarketPlanogram(
        store=store,
        catalog_codes=set(),
        products=products,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="",
                target_qty=2,
                price_rub=Decimal("15"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
                domain_product_id="prod-1",
            )
        ],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].domain_product_id == "prod-1"
    assert doc.lines[0].product_code == ""


def test_save_planogram_maps_legacy_code_to_one_domain_product() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="d-1",
            name="Кефир",
            catalog_code="2311",
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
        products=products,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            )
        ],
    )
    doc = store.get("701")
    assert doc is not None
    line = doc.lines[0]
    assert line.domain_product_id == "prod-1"
    assert line.product_code == ""


def test_save_planogram_keeps_legacy_code_when_domain_product_missing() -> None:
    store = InMemoryMicromarketPlanogramStore()
    SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
        products=FakeDomainProductStore(),
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=4,
                price_rub=Decimal("12"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            )
        ],
    )
    doc = store.get("701")
    assert doc is not None
    line = doc.lines[0]
    assert line.domain_product_id is None
    assert line.product_code == "2311"
    assert line.target_qty == 4


def test_save_planogram_accepts_hidden_domain_product() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-h",
            number="d-9",
            name="Скрытый",
            catalog_code=None,
            hidden=True,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    SaveMicromarketPlanogram(
        store=store,
        catalog_codes=set(),
        products=products,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
                domain_product_id="prod-h",
            )
        ],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].domain_product_id == "prod-h"


def _linked_line(domain_product_id: str, *, sort_order: int) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code="",
        target_qty=1,
        price_rub=Decimal("10"),
        active=True,
        sort_order=sort_order,
        kit_group_id=6348,
        domain_product_id=domain_product_id,
    )


def test_save_planogram_resets_published_status_when_domain_product_changes() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="d-1",
            name="Кефир",
            catalog_code=None,
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="prod-2",
            number="d-2",
            name="Ряженка",
            catalog_code=None,
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    SaveMicromarketPlanogram(
        store=store,
        catalog_codes=set(),
        products=products,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[_linked_line("prod-1", sort_order=0)],
    )
    current = store.get("701")
    assert current is not None
    store.upsert(
        MicromarketPlanogram(
            machine_code=current.machine_code,
            lines=current.lines,
            updated_at=current.updated_at,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_error="старая",
            shop_list_publication_id="pub-1",
        ),
    )
    SaveMicromarketPlanogram(
        store=store,
        catalog_codes=set(),
        products=products,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[_linked_line("prod-2", sort_order=0)],
    )
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].domain_product_id == "prod-2"
    assert doc.shop_list_status is ShopListPublishStatus.UNPUBLISHED
    assert doc.shop_list_error == ""
    assert doc.shop_list_publication_id == ""


def test_save_planogram_rejects_duplicate_domain_product_id() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="d-1",
            name="Кефир",
            catalog_code=None,
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    with pytest.raises(ValueError, match="duplicate domain_product_id"):
        SaveMicromarketPlanogram(
            store=store,
            catalog_codes=set(),
            products=products,
        ).execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                _linked_line("prod-1", sort_order=0),
                _linked_line("prod-1", sort_order=1),
            ],
        )
    assert store.get("701") is None


def test_save_planogram_rejects_unknown_domain_product_id() -> None:
    store = InMemoryMicromarketPlanogramStore()
    SaveMicromarketPlanogram(store=store, catalog_codes={"2311"}).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
            )
        ],
    )
    with pytest.raises(ValueError, match="unknown domain_product_id"):
        SaveMicromarketPlanogram(
            store=store,
            catalog_codes=set(),
            products=FakeDomainProductStore(),
        ).execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[_linked_line("missing", sort_order=0)],
        )
    doc = store.get("701")
    assert doc is not None
    assert doc.lines[0].product_code == "2311"


def test_save_planogram_rejects_legacy_code_outside_sellable_catalog() -> None:
    store = InMemoryMicromarketPlanogramStore()
    with pytest.raises(ValueError, match="unknown product_code"):
        SaveMicromarketPlanogram(
            store=store,
            catalog_codes={"2311"},
            products=FakeDomainProductStore(),
        ).execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                MicromarketPlanogramLine(
                    product_code="9999",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                )
            ],
        )
    assert store.get("701") is None


def test_save_planogram_rejects_legacy_code_that_matches_selected_product() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="d-1",
            name="Кефир",
            catalog_code="2311",
            hidden=False,
        )
    )
    store = InMemoryMicromarketPlanogramStore()
    SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
        products=products,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[_linked_line("prod-1", sort_order=0)],
    )
    with pytest.raises(ValueError, match="duplicate domain_product_id"):
        SaveMicromarketPlanogram(
            store=store,
            catalog_codes={"2311"},
            products=products,
        ).execute(
            shelves=_shelf(6348),
            machine_code="701",
            lines=[
                _linked_line("prod-1", sort_order=0),
                MicromarketPlanogramLine(
                    product_code="2311",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=1,
                    kit_group_id=6348,
                ),
            ],
        )
    doc = store.get("701")
    assert doc is not None
    assert len(doc.lines) == 1
    assert doc.lines[0].domain_product_id == "prod-1"


def test_save_planogram_persists_pending_exit_without_clearing_active() -> None:
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(store=store, catalog_codes={"2311"})
    save.execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=2,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
                pending_exit=True,
            ),
        ],
    )
    doc = GetMicromarketPlanogram(store=store).execute("701")
    assert doc is not None
    assert doc.lines[0].pending_exit is True
    assert doc.lines[0].active is True


def test_save_planogram_with_shelves_orders_pending_exit_after_normal_alpha() -> None:
    # edge: pending «Апельсин» раньше alpha, но группа pending_exit идёт после обычных;
    # несколько pending ниже обычных; ё→е в alpha-ключе без смены групп
    store = InMemoryMicromarketPlanogramStore()
    save = SaveMicromarketPlanogram(store=store, catalog_codes={"2311", "2312", "2313", "2314"})
    save.execute(
        machine_code="701",
        shelves=_shelf(6348),
        catalog_names={
            "2311": "Апельсин",
            "2312": "Банан",
            "2313": "Яблоко",
            "2314": "Ёлка",
        },
        lines=[
            MicromarketPlanogramLine(
                product_code="2311",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
                pending_exit=True,
            ),
            MicromarketPlanogramLine(
                product_code="2312",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=1,
                kit_group_id=6348,
                pending_exit=False,
            ),
            MicromarketPlanogramLine(
                product_code="2313",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=2,
                kit_group_id=6348,
                pending_exit=True,
            ),
            MicromarketPlanogramLine(
                product_code="2314",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=3,
                kit_group_id=6348,
                pending_exit=False,
            ),
        ],
    )
    doc = GetMicromarketPlanogram(store=store).execute("701")
    assert doc is not None
    # normal: Банан, Ёлка(=елка); pending: Апельсин, Яблоко
    assert [line.product_code for line in doc.lines] == ["2312", "2314", "2311", "2313"]
    assert [line.sort_order for line in doc.lines] == [0, 1, 2, 3]
    assert [line.pending_exit for line in doc.lines] == [False, False, True, True]


class _PendingExitPublisher:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def _pending_exit_line(
    code: str,
    *,
    pending_exit: bool = False,
    sort_order: int = 0,
    domain_product_id: str | None = None,
) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code=code,
        target_qty=1,
        price_rub=Decimal("10"),
        active=True,
        sort_order=sort_order,
        kit_group_id=6348,
        domain_product_id=domain_product_id,
        pending_exit=pending_exit,
    )


def _seed_last_factual(
    stock_store: InMemoryMicromarketDeviceStockStore,
    quantities: dict[str, Decimal],
    *,
    inventory_id: str,
) -> None:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        quantities=quantities,
        inventory_id=inventory_id,
        partial=True,
    )
    stock_store.save(stock)


def test_save_removes_pending_exit_line_when_last_factual_is_zero_and_enqueues_publish() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="d-1",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="prod-2",
            number="d-2",
            name="Вода",
            catalog_code="2312",
            hidden=False,
        )
    )
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    publisher = _PendingExitPublisher()
    _seed_last_factual(stock_store, {"d-1": Decimal("0")}, inventory_id="inv-zero-1")
    SaveMicromarketPlanogram(
        store=planogram_store,
        catalog_codes={"2311", "2312"},
        products=products,
        stock_store=stock_store,
        publisher=publisher,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            _pending_exit_line("", pending_exit=True, sort_order=0, domain_product_id="prod-1"),
            _pending_exit_line("", pending_exit=False, sort_order=1, domain_product_id="prod-2"),
        ],
    )
    doc = GetMicromarketPlanogram(store=planogram_store).execute("701")
    assert doc is not None
    assert [line.domain_product_id for line in doc.lines] == ["prod-2"]
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)
    assert event.machine_code == "701"


def test_save_keeps_pending_exit_line_when_last_factual_missing_or_nonzero() -> None:
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    publisher = _PendingExitPublisher()
    save = SaveMicromarketPlanogram(
        store=planogram_store,
        catalog_codes={"2311", "2312"},
        stock_store=stock_store,
        publisher=publisher,
    )
    save.execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[_pending_exit_line("2311", pending_exit=True)],
    )
    missing = GetMicromarketPlanogram(store=planogram_store).execute("701")
    assert missing is not None
    assert missing.lines[0].product_code == "2311"
    assert missing.lines[0].pending_exit is True
    assert missing.lines[0].active is True
    assert publisher.events == []

    _seed_last_factual(stock_store, {"2312": Decimal("3")}, inventory_id="inv-nonzero-1")
    save.execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[_pending_exit_line("2312", pending_exit=True)],
    )
    nonzero = GetMicromarketPlanogram(store=planogram_store).execute("701")
    assert nonzero is not None
    assert nonzero.lines[0].product_code == "2312"
    assert nonzero.lines[0].pending_exit is True
    assert nonzero.lines[0].active is True
    assert publisher.events == []


def test_save_keeps_line_with_factual_zero_when_not_pending_exit() -> None:
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    publisher = _PendingExitPublisher()
    _seed_last_factual(stock_store, {"2311": Decimal("0")}, inventory_id="inv-keep-1")
    SaveMicromarketPlanogram(
        store=planogram_store,
        catalog_codes={"2311"},
        stock_store=stock_store,
        publisher=publisher,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[_pending_exit_line("2311", pending_exit=False)],
    )
    doc = GetMicromarketPlanogram(store=planogram_store).execute("701")
    assert doc is not None
    assert len(doc.lines) == 1
    assert doc.lines[0].product_code == "2311"
    assert doc.lines[0].pending_exit is False
    assert doc.lines[0].active is True
    assert publisher.events == []


def test_save_removes_pending_exit_line_without_publisher() -> None:
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_last_factual(stock_store, {"2311": Decimal("0")}, inventory_id="inv-nopub-1")
    SaveMicromarketPlanogram(
        store=planogram_store,
        catalog_codes={"2311"},
        stock_store=stock_store,
        publisher=None,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[_pending_exit_line("2311", pending_exit=True)],
    )
    doc = GetMicromarketPlanogram(store=planogram_store).execute("701")
    assert doc is not None
    assert doc.lines == ()


def test_save_removes_pending_exit_domain_line_using_domain_number() -> None:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="d-1",
            name="Салат",
            catalog_code="2311",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="prod-2",
            number="d-2",
            name="Вода",
            catalog_code="2312",
            hidden=False,
        )
    )
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    publisher = _PendingExitPublisher()
    _seed_last_factual(stock_store, {"d-1": Decimal("0")}, inventory_id="inv-dom-1")
    SaveMicromarketPlanogram(
        store=planogram_store,
        catalog_codes={"2311", "2312"},
        products=products,
        stock_store=stock_store,
        publisher=publisher,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            _pending_exit_line("", pending_exit=True, sort_order=0, domain_product_id="prod-1"),
            _pending_exit_line("", pending_exit=False, sort_order=1, domain_product_id="prod-2"),
        ],
    )
    doc = GetMicromarketPlanogram(store=planogram_store).execute("701")
    assert doc is not None
    assert [line.domain_product_id for line in doc.lines] == ["prod-2"]
    assert len(publisher.events) == 1


def test_save_clear_pending_exit_writes_journal_pending_exit() -> None:
    # happy: save clear pending_exit → journal pending_exit (+ effects)
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="d-1",
            name="One",
            catalog_code="2311",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="prod-2",
            number="d-2",
            name="Two",
            catalog_code="2312",
            hidden=False,
        )
    )
    planogram_store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    publisher = _PendingExitPublisher()
    journal = InMemoryShopListPublishJournal()
    _seed_last_factual(stock_store, {"d-1": Decimal("0")}, inventory_id="inv-zero-j")
    SaveMicromarketPlanogram(
        store=planogram_store,
        catalog_codes={"2311", "2312"},
        products=products,
        stock_store=stock_store,
        publisher=publisher,
        journal=journal,
    ).execute(
        shelves=_shelf(6348),
        machine_code="701",
        lines=[
            _pending_exit_line("", pending_exit=True, sort_order=0, domain_product_id="prod-1"),
            _pending_exit_line("", pending_exit=False, sort_order=1, domain_product_id="prod-2"),
        ],
    )
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].trigger is ShopListPublishTrigger.PENDING_EXIT
    assert rows[0].status is ShopListPublishJournalStatus.RUNNING
    assert len(publisher.events) == 1
