from __future__ import annotations

import io
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.micromarket_loading.supply_order_category import (
    SupplyOrderCategoryFactsFetchFailed,
    SupplyOrderCategoryProductFacts,
)
from src.application.micromarket_loading.supply_order_forecast import (
    AlwaysUnavailableSupplyOrderForecast,
)
from src.application.micromarket_loading.supply_orders import (
    CreateMicromarketSupplyOrder,
    DeleteMicromarketSupplyOrder,
    DownloadMicromarketSupplyOrder,
    ListMicromarketSupplyOrders,
    LiveNeedLine,
    LiveNeedMachine,
    ResolveLoadingNeed,
    SupplyOrderCreated,
    SupplyOrderEmptySelection,
    SupplyOrderInvalidArrival,
    SupplyOrderMissingShelfLife,
    SupplyOrderMsUnavailable,
    SupplyOrderNoPositiveNeed,
    SupplyOrderNotFound,
    SupplyOrderProductsNotLinked,
)
from src.application.product_identity.models import DomainProduct
from src.application.product_identity.procurement_mirror import ProcurementMirror
from src.domain.micromarket_loading.supply_order import (
    MicromarketSupplyOrder,
    MicromarketSupplyOrderLine,
    MicromarketSupplyOrderMachine,
)
from src.infrastructure.product_identity.memory_procurement_mirror_store import (
    MemoryProcurementMirrorStore,
)
from src.infrastructure.testing.micromarket_loading_fakes import InMemoryMicromarketSupplyOrderStore

_T0 = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
_T1 = datetime(2026, 10, 9, 11, 0, tzinfo=UTC)
_ARRIVAL = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
_SNACKS = "4c2738f1-f43a-11ef-0a80-1a2b002150a4"
_READY = "7203a901-b1b2-11f1-0a80-115a00344501"


class FakeForecastPort:
    def __init__(self, qty_by_code: dict[str, Decimal | None] | None = None) -> None:
        self._qty_by_code = qty_by_code or {}
        self.calls: list[dict[str, object]] = []

    def forecast_qty(
        self,
        *,
        machine_id: str,
        product_code: str,
        category: Literal[2, 3],
        horizon_start: datetime,
        horizon_end: datetime,
        shelf_qty: Decimal,
        target_qty: Decimal,
    ) -> Decimal | None:
        self.calls.append(
            {
                "machine_id": machine_id,
                "product_code": product_code,
                "category": category,
                "shelf_qty": shelf_qty,
                "target_qty": target_qty,
            },
        )
        if product_code in self._qty_by_code:
            return self._qty_by_code[product_code]
        return None


class FakeCategoryFactsPort:
    def __init__(
        self,
        facts: Sequence[SupplyOrderCategoryProductFacts] = (),
        *,
        fail: bool = False,
    ) -> None:
        self._facts = tuple(facts)
        self._fail = fail

    def fetch_by_catalog_codes(
        self,
        catalog_codes: Sequence[str],
    ) -> Sequence[SupplyOrderCategoryProductFacts] | SupplyOrderCategoryFactsFetchFailed:
        if self._fail:
            return SupplyOrderCategoryFactsFetchFailed()
        wanted = set(catalog_codes)
        return tuple(row for row in self._facts if row.catalog_code in wanted)


def _ready_facts(*catalog_codes: str, days: int = 7) -> FakeCategoryFactsPort:
    return FakeCategoryFactsPort(
        tuple(
            SupplyOrderCategoryProductFacts(
                catalog_code=code,
                folder_ancestor_ids=(_READY,),
                shelf_life_days=days,
            )
            for code in catalog_codes
        ),
    )


def _xlsx_blob(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
        shared = ""
        if "xl/sharedStrings.xml" in zf.namelist():
            shared = zf.read("xl/sharedStrings.xml").decode()
        return sheet + shared


def _link_products(*numbers: str) -> FakeDomainProductStore:
    store = FakeDomainProductStore()
    for index, number in enumerate(numbers, start=1):
        store.insert(
            DomainProduct(
                domain_product_id=f"dp-{index}",
                number=number,
                name=f"Name {number}",
                catalog_code=f"ms-{number}",
                hidden=False,
            ),
        )
    return store


def _create(
    store: InMemoryMicromarketSupplyOrderStore,
    *,
    products: FakeDomainProductStore | None = None,
    mirrors: MemoryProcurementMirrorStore | None = None,
    clock: object | None = None,
    category_facts: FakeCategoryFactsPort | None = None,
    forecast: object | None = None,
) -> CreateMicromarketSupplyOrder:
    resolved_products = products if products is not None else _link_products("2311", "2312")
    if category_facts is None:
        codes = []
        # default: all linked catalog codes as ready meals with days=7
        for number in ("2311", "2312", "9999"):
            product = resolved_products.get_by_number(number)
            if product is not None and product.catalog_code:
                codes.append(product.catalog_code)
        category_facts = _ready_facts(*codes, days=7)
    return CreateMicromarketSupplyOrder(
        store=store,
        clock=clock if clock is not None else (lambda: _T0),
        products=resolved_products,
        category_facts=category_facts,
        snacks_folder_id=_SNACKS,
        ready_meals_folder_id=_READY,
        shelf_life_days_threshold=7,
        forecast=forecast if forecast is not None else AlwaysUnavailableSupplyOrderForecast(),
        mirrors=mirrors,
    )


def test_create_persists_snapshot_and_xlsx_aggregate() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    clock = iter((_T0,)).__next__
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="ms-2311",
            supplier_id="agent-1",
            supplier_name="ООО Поставщик",
            last_buy_price=Decimal("12.50"),
            supply_moment=_T0,
            synced_at=_T0,
            package_quantity=Decimal("6"),
            supplier_product_name="Салат у поставщика",
        ),
    )
    result = _create(store, mirrors=mirrors, clock=clock).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(
                    LiveNeedLine("2311", Decimal("3"), Decimal("0"), Decimal("0"), "Салат"),
                    LiveNeedLine("2312", Decimal("0"), Decimal("0"), Decimal("0"), "Вода"),
                ),
            ),
            LiveNeedMachine(
                machine_id="702",
                lines=(LiveNeedLine("2311", Decimal("2"), Decimal("0"), Decimal("0"), "Салат"),),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderCreated)
    assert result.order.order_id
    assert result.order.created_at == _T0
    assert store.get(result.order.order_id) == result.order
    by_machine = {m.machine_id: m for m in result.order.machines}
    line = by_machine["701"].lines[0]
    assert line.product_code == "2311"
    assert line.need_qty == Decimal("3")
    assert line.category == 3
    assert line.supplier_name == "ООО Поставщик"
    assert line.last_buy_price == Decimal("12.50")
    assert line.package_quantity == Decimal("6")
    assert line.supplier_product_name == "Салат у поставщика"
    blob = _xlsx_blob(result.xlsx)
    assert "2311" in blob
    assert "Салат" in blob
    assert "5" in blob
    assert "ООО Поставщик" in blob
    assert "12.5" in blob
    assert "6" in blob
    assert "Салат у поставщика" in blob
    assert "поставщик" in blob
    assert "цена последнего закупа" in blob
    assert "количество в упаковке" in blob
    assert "название у поставщика" in blob
    assert "2312" not in blob


def test_download_rebuilds_xlsx_from_snapshot_after_mirror_change() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    order = MicromarketSupplyOrder(
        order_id="so-1",
        created_at=_T0,
        expected_arrival_at=_ARRIVAL,
        machines=(
            MicromarketSupplyOrderMachine(
                machine_id="701",
                lines=(
                    MicromarketSupplyOrderLine(
                        product_code="2311",
                        need_qty=Decimal("4"),
                        category=2,
                        name="Салат",
                        supplier_name="Старый",
                        last_buy_price=Decimal("1"),
                    ),
                ),
            ),
        ),
    )
    store.save(order)
    first = DownloadMicromarketSupplyOrder(store=store).execute("so-1")
    assert isinstance(first, bytes)
    mirrors = MemoryProcurementMirrorStore()
    mirrors.upsert(
        ProcurementMirror(
            catalog_code="ms-2311",
            supplier_id="x",
            supplier_name="Новый",
            last_buy_price=Decimal("99"),
            supply_moment=_T1,
            synced_at=_T1,
        ),
    )
    second = DownloadMicromarketSupplyOrder(store=store).execute("so-1")
    assert second == first
    blob = _xlsx_blob(first)
    assert "4" in blob
    assert "Старый" in blob
    assert "Новый" not in blob


def test_create_allows_empty_procurement_cells_when_mirror_missing() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    result = _create(store).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(LiveNeedLine("2311", Decimal("2"), Decimal("0"), Decimal("0"), "Салат"),),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderCreated)
    line = result.order.machines[0].lines[0]
    assert line.supplier_name is None
    assert line.last_buy_price is None
    assert line.category == 3
    blob = _xlsx_blob(result.xlsx)
    assert "поставщик" in blob
    assert "Салат" in blob


def test_create_rejects_unlinked_without_persist() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="dp-1",
            number="2311",
            name="Салат",
            catalog_code=None,
            hidden=False,
        ),
    )
    result = _create(store, products=products).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(
                    LiveNeedLine("2311", Decimal("2"), Decimal("0"), Decimal("0"), "Салат"),
                    LiveNeedLine("9999", Decimal("1"), Decimal("0"), Decimal("0"), "Нет товара"),
                ),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderProductsNotLinked)
    assert ("2311", "Салат") in result.items
    assert ("9999", "Нет товара") in result.items
    assert store.list_newest() == ()


def test_list_newest_first() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    older = MicromarketSupplyOrder(
        order_id="old",
        created_at=_T0,
        expected_arrival_at=_ARRIVAL,
        machines=(
            MicromarketSupplyOrderMachine(
                machine_id="701",
                lines=(
                    MicromarketSupplyOrderLine(
                        product_code="2311",
                        need_qty=Decimal("1"),
                        category=2,
                        name="A",
                    ),
                ),
            ),
        ),
    )
    newer = MicromarketSupplyOrder(
        order_id="new",
        created_at=_T1,
        expected_arrival_at=_ARRIVAL,
        machines=(
            MicromarketSupplyOrderMachine(
                machine_id="702",
                lines=(
                    MicromarketSupplyOrderLine(
                        product_code="2311",
                        need_qty=Decimal("2"),
                        category=3,
                        name="A",
                    ),
                ),
            ),
        ),
    )
    store.save(older)
    store.save(newer)
    listed = ListMicromarketSupplyOrders(store=store).execute()
    assert [item.order_id for item in listed] == ["new", "old"]


def test_create_merges_multi_machine_lines_and_omits_zeros() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    result = _create(store).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(
                    LiveNeedLine("2311", Decimal("1"), Decimal("0"), Decimal("0"), "Салат"),
                    LiveNeedLine("2312", Decimal("0"), Decimal("0"), Decimal("0"), "Вода"),
                ),
            ),
            LiveNeedMachine(
                machine_id="702",
                lines=(LiveNeedLine("2311", Decimal("4"), Decimal("0"), Decimal("0"), "Салат"),),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderCreated)
    blob = _xlsx_blob(result.xlsx)
    assert "5" in blob
    assert "2312" not in blob


def test_create_rejects_empty_selection_without_persist() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    result = _create(store).execute(
        machines=(),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderEmptySelection)
    assert store.list_newest() == ()


def test_create_rejects_all_zero_need_without_persist() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    result = _create(store).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(LiveNeedLine("2311", Decimal("0"), Decimal("0"), Decimal("0"), "Салат"),),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderNoPositiveNeed)
    assert store.list_newest() == ()


def test_download_and_delete_unknown_return_not_found() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    assert isinstance(
        DownloadMicromarketSupplyOrder(store=store).execute("missing"),
        SupplyOrderNotFound,
    )
    assert isinstance(
        DeleteMicromarketSupplyOrder(store=store).execute("missing"),
        SupplyOrderNotFound,
    )


def test_delete_removes_document() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    order = MicromarketSupplyOrder(
        order_id="so-del",
        created_at=_T0,
        expected_arrival_at=_ARRIVAL,
        machines=(
            MicromarketSupplyOrderMachine(
                machine_id="701",
                lines=(
                    MicromarketSupplyOrderLine(
                        product_code="2311",
                        need_qty=Decimal("1"),
                        category=2,
                        name="A",
                    ),
                ),
            ),
        ),
    )
    store.save(order)
    result = DeleteMicromarketSupplyOrder(store=store).execute("so-del")
    assert result is None
    assert store.get("so-del") is None


def test_resolve_need_uses_last_order_then_live() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    store.save(
        MicromarketSupplyOrder(
            order_id="older",
            created_at=_T0,
            expected_arrival_at=_ARRIVAL,
            machines=(
                MicromarketSupplyOrderMachine(
                    machine_id="701",
                    lines=(
                        MicromarketSupplyOrderLine(
                            product_code="2311",
                            need_qty=Decimal("9"),
                            category=2,
                            name="Салат",
                        ),
                    ),
                ),
            ),
        ),
    )
    store.save(
        MicromarketSupplyOrder(
            order_id="newer",
            created_at=_T1,
            expected_arrival_at=_ARRIVAL,
            machines=(
                MicromarketSupplyOrderMachine(
                    machine_id="701",
                    lines=(
                        MicromarketSupplyOrderLine(
                            product_code="2311",
                            need_qty=Decimal("4"),
                            category=3,
                            name="Салат",
                        ),
                    ),
                ),
            ),
        ),
    )
    resolved = ResolveLoadingNeed(store=store).execute(
        machine_id="701",
        live_need_by_code={"2311": Decimal("7"), "2312": Decimal("2")},
    )
    by_code = {line.product_code: line for line in resolved}
    assert by_code["2311"].need_qty == Decimal("4")
    assert by_code["2311"].need_from_live is False
    assert by_code["2312"].need_qty == Decimal("2")
    assert by_code["2312"].need_from_live is True


def test_resolve_need_all_live_after_delete_last_order() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    store.save(
        MicromarketSupplyOrder(
            order_id="only",
            created_at=_T0,
            expected_arrival_at=_ARRIVAL,
            machines=(
                MicromarketSupplyOrderMachine(
                    machine_id="701",
                    lines=(
                        MicromarketSupplyOrderLine(
                            product_code="2311",
                            need_qty=Decimal("4"),
                            category=2,
                            name="Салат",
                        ),
                    ),
                ),
            ),
        ),
    )
    DeleteMicromarketSupplyOrder(store=store).execute("only")
    resolved = ResolveLoadingNeed(store=store).execute(
        machine_id="701",
        live_need_by_code={"2311": Decimal("3")},
    )
    assert len(resolved) == 1
    assert resolved[0].need_qty == Decimal("3")
    assert resolved[0].need_from_live is True


def test_create_filters_snacks_and_keeps_ready_categories() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    products = _link_products("2311", "2312", "2313", "2314")
    facts = FakeCategoryFactsPort(
        (
            SupplyOrderCategoryProductFacts("ms-2311", (_SNACKS,), 1),
            SupplyOrderCategoryProductFacts("ms-2312", (_READY,), 7),
            SupplyOrderCategoryProductFacts("ms-2313", (_READY,), 10),
            SupplyOrderCategoryProductFacts("ms-2314", ("other",), 3),
        ),
    )
    result = _create(store, products=products, category_facts=facts).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(
                    LiveNeedLine("2311", Decimal("2"), Decimal("0"), Decimal("0"), "Снек"),
                    LiveNeedLine("2312", Decimal("3"), Decimal("0"), Decimal("0"), "Короткий"),
                    LiveNeedLine("2313", Decimal("4"), Decimal("0"), Decimal("0"), "Длинный"),
                    LiveNeedLine("2314", Decimal("5"), Decimal("0"), Decimal("0"), "Мимо"),
                ),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderCreated)
    codes = {line.product_code: line.category for line in result.order.machines[0].lines}
    assert codes == {"2312": 3, "2313": 2}
    blob = _xlsx_blob(result.xlsx)
    assert "2312" in blob
    assert "2313" in blob
    assert "2311" not in blob
    assert "2314" not in blob


def test_create_only_snacks_returns_no_positive_need() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    products = _link_products("2311")
    facts = FakeCategoryFactsPort(
        (SupplyOrderCategoryProductFacts("ms-2311", (_SNACKS,), None),),
    )
    result = _create(store, products=products, category_facts=facts).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(LiveNeedLine("2311", Decimal("2"), Decimal("0"), Decimal("0"), "Снек"),),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderNoPositiveNeed)
    assert store.list_newest() == ()


def test_create_missing_shelf_life_blocks_without_persist() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    products = _link_products("2311", "2312")
    facts = FakeCategoryFactsPort(
        (
            SupplyOrderCategoryProductFacts("ms-2311", (_READY,), None),
            SupplyOrderCategoryProductFacts("ms-2312", (_READY,), 5),
        ),
    )
    result = _create(store, products=products, category_facts=facts).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(
                    LiveNeedLine("2311", Decimal("2"), Decimal("0"), Decimal("0"), "Без дней"),
                    LiveNeedLine("2312", Decimal("3"), Decimal("0"), Decimal("0"), "С днями"),
                ),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderMissingShelfLife)
    assert ("2311", "Без дней") in result.items
    assert store.list_newest() == ()


def test_create_ms_unavailable_fail_closed() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    result = _create(store, category_facts=FakeCategoryFactsPort(fail=True)).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(LiveNeedLine("2311", Decimal("2"), Decimal("0"), Decimal("0"), "Салат"),),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderMsUnavailable)
    assert store.list_newest() == ()


def test_create_rejects_missing_or_past_arrival() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    uc = _create(store)
    machines = (
        LiveNeedMachine(
            machine_id="701",
            lines=(LiveNeedLine("2311", Decimal("2"), Decimal("0"), Decimal("0"), "Салат"),),
        ),
    )
    assert isinstance(
        uc.execute(machines=machines, expected_arrival_at=None),
        SupplyOrderInvalidArrival,
    )
    assert isinstance(
        uc.execute(machines=machines, expected_arrival_at=_T0),
        SupplyOrderInvalidArrival,
    )
    assert store.list_newest() == ()


def test_create_adds_forecast_to_need_qty() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    forecast = FakeForecastPort({"2311": Decimal("4")})
    result = _create(store, forecast=forecast).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(LiveNeedLine("2311", Decimal("3"), Decimal("2"), Decimal("5"), "Салат"),),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderCreated)
    line = result.order.machines[0].lines[0]
    assert line.gap_qty == Decimal("3")
    assert line.need_qty == Decimal("7")
    assert line.forecast_qty == Decimal("4")
    assert line.need_qty == line.gap_qty + line.forecast_qty
    assert forecast.calls == [
        {
            "machine_id": "701",
            "product_code": "2311",
            "category": 3,
            "shelf_qty": Decimal("2"),
            "target_qty": Decimal("5"),
        },
    ]
    assert result.order.expected_arrival_at == _ARRIVAL
    assert result.forecast_unavailable_items == ()
    blob = _xlsx_blob(result.xlsx)
    assert "прибытие" in blob
    assert _ARRIVAL.isoformat() in blob


def test_create_row_fallback_when_forecast_unavailable() -> None:
    store = InMemoryMicromarketSupplyOrderStore()
    forecast = FakeForecastPort({"2311": Decimal("2"), "2312": None})
    products = _link_products("2311", "2312")
    result = _create(store, products=products, forecast=forecast).execute(
        machines=(
            LiveNeedMachine(
                machine_id="701",
                lines=(
                    LiveNeedLine("2311", Decimal("1"), Decimal("0"), Decimal("0"), "A"),
                    LiveNeedLine("2312", Decimal("5"), Decimal("0"), Decimal("0"), "B"),
                ),
            ),
        ),
        expected_arrival_at=_ARRIVAL,
    )
    assert isinstance(result, SupplyOrderCreated)
    by_code = {line.product_code: line for line in result.order.machines[0].lines}
    assert by_code["2311"].gap_qty == Decimal("1")
    assert by_code["2311"].need_qty == Decimal("3")
    assert by_code["2311"].forecast_qty == Decimal("2")
    assert by_code["2312"].gap_qty == Decimal("5")
    assert by_code["2312"].need_qty == Decimal("5")
    assert by_code["2312"].forecast_qty == Decimal("0")
    assert result.forecast_unavailable_items == (("2312", "B"),)
