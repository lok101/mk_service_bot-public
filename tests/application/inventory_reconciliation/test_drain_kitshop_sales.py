from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.inventory_reconciliation.drain_kitshop_sales import (
    DrainKitShopSalesBacklog,
)
from src.application.master_data import MachineKind
from src.application.micromarket_loading import ApplyMicromarketSaleToStock
from src.application.product_identity import (
    CatalogProduct,
    KitShopSaleResolve,
    create_domain_product,
    link_domain_product,
    resolve_kit_shop_sale_code,
)
from src.domain.ids import MachineId
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.infrastructure.testing.kitshop_ingest_fakes import (
    FakeKitShopCompanyResolver,
    FakeKitShopSaleDetail,
    FakeKitShopSalePosition,
    FakeKitShopSalesGateway,
    InMemoryKitShopSaleReceiptStore,
    InMemoryKitShopSalesBacklogStore,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    StaticMachineKindLookup,
)
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore


def _get_sale(store: InMemoryMachineSalesStore, source_id: str):
    return store._by_source_id.get(source_id)


def _seed_stock(stock: InMemoryMicromarketDeviceStockStore) -> None:
    device = MicromarketDeviceStock(machine_code="701")
    device.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={"2311": Decimal("10")},
        inventory_id="inv-1",
    )
    stock.save(device)


def _seed_stock_number(
    stock: InMemoryMicromarketDeviceStockStore,
    *,
    number: str,
) -> None:
    device = MicromarketDeviceStock(machine_code="701")
    device.apply_inventory(
        as_of=datetime(2026, 9, 1, tzinfo=UTC),
        quantities={number: Decimal("10")},
        inventory_id="inv-1",
    )
    stock.save(device)


def _drain_uc(
    *,
    gateway,
    backlog,
    sales,
    stock,
    receipts=None,
    domain_product_identity_enabled: bool = False,
    resolve_sale_code: Callable[[str], KitShopSaleResolve] | None = None,
    occupancy_store=None,
    after_occupancy_rebuild=None,
):
    kinds = StaticMachineKindLookup({"701": MachineKind.MICRO_MARKET})
    apply_sale = ApplyMicromarketSaleToStock(stock_store=stock, machine_kind_lookup=kinds)
    if receipts is None:
        receipts = InMemoryKitShopSaleReceiptStore()
    return DrainKitShopSalesBacklog(
        gateway=gateway,
        backlog=backlog,
        sales_store=sales,
        apply_micromarket_sale=apply_sale,
        company_resolver=FakeKitShopCompanyResolver({1: 7}),
        receipts=receipts,
        domain_product_identity_enabled=domain_product_identity_enabled,
        resolve_sale_code=resolve_sale_code,
        occupancy_store=occupancy_store,
        after_occupancy_rebuild=after_occupancy_rebuild,
    )


def test_drain_persists_and_deducts_micromarket() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    result = uc.execute(limit=1)
    assert result.deducted == 1
    row = _get_sale(sales, "kitshop:100:1")
    assert row is not None
    assert row.sale_kind == "micromarket"
    assert row.machine_id == MachineId("701")
    assert row.product_code == "2311"
    assert row.kit_vending_machine_id is None
    assert row.occurred_at.tzinfo is not None
    loaded = stock.load("701")
    assert loaded is not None
    assert loaded.has_seen_sale_source_id("kitshop:100:1")
    assert loaded.qty("2311") == Decimal("9")
    assert backlog.get_status(100) == "done"


def test_drain_two_positions_two_source_ids() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.two_positions(sale_id=100, shop_name="Офис [701]")
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    result = uc.execute(limit=1)
    assert _get_sale(sales, "kitshop:100:1") is not None
    assert _get_sale(sales, "kitshop:100:2") is not None
    assert result.deducted == 2


def test_drain_binds_via_shop_name_not_device_id() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    uc.execute(limit=1)
    row = _get_sale(sales, "kitshop:100:1")
    assert row is not None
    assert row.machine_id == MachineId("701")
    assert str(row.machine_id.value) != "999"


def test_drain_holds_empty_vendor_code() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    result = uc.execute(limit=1)
    assert result.deducted == 0
    assert _get_sale(sales, "kitshop:100:1") is None
    assert backlog.get_status(100) == "hold"


def test_drain_holds_missing_machine_code() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис без кода",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    result = uc.execute(limit=1)
    assert result.deducted == 0
    assert backlog.get_status(100) == "hold"
    assert result.affected_machine_ids == ()


def test_drain_holds_company_miss() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    kinds = StaticMachineKindLookup({"701": MachineKind.MICRO_MARKET})
    apply_sale = ApplyMicromarketSaleToStock(stock_store=stock, machine_kind_lookup=kinds)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=99,
    )
    uc = DrainKitShopSalesBacklog(
        gateway=gateway,
        backlog=backlog,
        sales_store=sales,
        apply_micromarket_sale=apply_sale,
        company_resolver=FakeKitShopCompanyResolver({}),
        receipts=InMemoryKitShopSaleReceiptStore(),
    )
    result = uc.execute(limit=1)
    assert result.deducted == 0
    assert backlog.get_status(100) == "hold"
    assert result.affected_machine_ids == ()


def test_drain_result_includes_affected_machine_ids() -> None:
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    result = uc.execute(limit=1)
    assert result.affected_machine_ids == (MachineId("701"),)


def test_drain_saves_receipt_before_sales() -> None:
    # happy: save снимка происходит, пока в учёте ещё пусто
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
        price=Decimal("190"),
    )

    class _Receipts:
        def __init__(self) -> None:
            self.saved = False

        def load(self, sale_id: int) -> dict[str, object] | None:
            del sale_id
            return {"stub": True} if self.saved else None

        def save_if_absent(self, *, sale_id: int, payload: dict[str, object]) -> None:
            del sale_id, payload
            assert sales._by_source_id == {}
            self.saved = True

    receipts = _Receipts()
    uc = _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        receipts=receipts,
    )
    uc.execute(limit=1)
    assert receipts.saved is True
    assert gateway.detail_fetches == 1
    assert _get_sale(sales, "kitshop:100:1") is not None


def test_drain_receipt_save_failure_leaves_pending() -> None:
    # error: запись снимка упала → нет учёта, статус pending, не done
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )

    class _Boom:
        def load(self, sale_id: int) -> dict[str, object] | None:
            del sale_id
            return None

        def save_if_absent(self, *, sale_id: int, payload: dict[str, object]) -> None:
            del sale_id, payload
            raise RuntimeError("receipt write failed")

    uc = _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        receipts=_Boom(),
    )
    result = uc.execute(limit=1)
    assert result.done == 0
    assert result.held == 0
    assert backlog.get_status(100) == "pending"
    assert _get_sale(sales, "kitshop:100:1") is None


def test_drain_hold_retry_skips_second_fetch() -> None:
    # idempotency: hold из-за пустого VendorCode, затем код появился
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    receipts = InMemoryKitShopSaleReceiptStore()
    uc = _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        receipts=receipts,
    )
    first = uc.execute(limit=1)
    assert first.held == 1
    assert gateway.detail_fetches == 1
    assert receipts.load(100) is not None
    gateway._vendor_codes[20] = "2311"
    second = uc.execute(limit=1)
    assert gateway.detail_fetches == 1
    assert second.done == 1
    assert _get_sale(sales, "kitshop:100:1") is not None


def test_drain_quantity_two_is_one_sale_and_one_deduct() -> None:
    # happy: Price не делится на Quantity; deduct один, qty=2
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("2"),
        kit_company_id=1,
        price=Decimal("190"),
    )
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    result = uc.execute(limit=1)
    row = _get_sale(sales, "kitshop:100:1")
    assert row is not None
    assert row.quantity == Decimal("2")
    assert row.price == Decimal("190")
    assert _get_sale(sales, "kitshop:100:1#2") is None
    assert result.deducted == 1
    loaded = stock.load("701")
    assert loaded is not None
    assert loaded.qty("2311") == Decimal("8")


def test_drain_quantity_below_one_holds_invalid_quantity() -> None:
    # error
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("0"),
        kit_company_id=1,
        price=Decimal("190"),
    )
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    result = uc.execute(limit=1)
    assert result.deducted == 0
    assert result.held == 1
    assert backlog.get_status(100) == "hold"
    assert backlog._hold_reason[100] == "invalid_quantity"
    assert _get_sale(sales, "kitshop:100:1") is None


def test_drain_mixed_invalid_quantity_keeps_valid_row() -> None:
    # edge: одна позиция годная, вторая Quantity < 1 → вставка годной, hold invalid_quantity
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.two_positions(sale_id=100, shop_name="Офис [701]")
    old = gateway._details[100]
    gateway._details[100] = FakeKitShopSaleDetail(
        sale_id=old.sale_id,
        company_id=old.company_id,
        shop_id=old.shop_id,
        device_id=old.device_id,
        sale_datetime=old.sale_datetime,
        positions=(
            old.positions[0],
            FakeKitShopSalePosition(
                position_id=2,
                product_id=21,
                quantity=Decimal("0"),
                price=Decimal("50"),
            ),
        ),
    )
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    result = uc.execute(limit=1)
    assert _get_sale(sales, "kitshop:100:1") is not None
    assert _get_sale(sales, "kitshop:100:2") is None
    assert result.held == 1
    assert backlog._hold_reason[100] == "invalid_quantity"


class _RecordingAlert:
    def __init__(self) -> None:
        self.held: list[tuple[int, tuple[str, ...]]] = []
        self.failed: list[tuple[str, str]] = []

    def notify_held(self, *, count: int, reasons: tuple[str, ...]) -> None:
        self.held.append((count, reasons))

    def notify_phase_failed(self, *, phase: str, exception_type: str) -> None:
        self.failed.append((phase, exception_type))


def test_drain_hold_notifies_when_count_reaches_min() -> None:
    # happy: один hold при пороге 1
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис без кода",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    alerts = _RecordingAlert()
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    uc.unresolved_alert_min = 1
    uc.unresolved_alert_notifier = alerts
    uc.execute(limit=1)
    assert alerts.held == [(1, ("no_machine_code",))]


def test_drain_hold_silent_below_min() -> None:
    # edge
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис без кода",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    alerts = _RecordingAlert()
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    uc.unresolved_alert_min = 2
    uc.unresolved_alert_notifier = alerts
    uc.execute(limit=1)
    assert alerts.held == []


def test_drain_success_does_not_notify() -> None:
    # edge: успешный тик молчит
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    alerts = _RecordingAlert()
    uc = _drain_uc(gateway=gateway, backlog=backlog, sales=sales, stock=stock)
    uc.unresolved_alert_min = 1
    uc.unresolved_alert_notifier = alerts
    uc.execute(limit=1)
    assert alerts.held == []
    assert alerts.failed == []


def test_drain_source_does_not_import_master_data() -> None:
    text = Path(
        "src/application/inventory_reconciliation/drain_kitshop_sales.py",
    ).read_text(encoding="utf-8")
    assert "master_data" not in text


def test_drain_recognized_deducts_number() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    product = create_domain_product("Молоко", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)

    def resolve(code: str):
        return resolve_kit_shop_sale_code(code, store=store, lookup=lookup)

    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock_number(stock, number=product.number)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code=product.number,
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    result = _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        domain_product_identity_enabled=True,
        resolve_sale_code=resolve,
    ).execute(limit=1)
    row = _get_sale(sales, "kitshop:100:1")
    assert result.deducted == 1
    assert row is not None
    assert row.product_code == product.number
    assert row.domain_product_id == product.domain_product_id
    loaded = stock.load("701")
    assert loaded is not None
    assert loaded.qty(product.number) == Decimal("9")


def test_drain_catalog_alias_deducts_same_number(caplog) -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    product = create_domain_product("Молоко", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)

    def resolve(code: str):
        return resolve_kit_shop_sale_code(code, store=store, lookup=lookup)

    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock_number(stock, number=product.number)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    with caplog.at_level("INFO"):
        result = _drain_uc(
            gateway=gateway,
            backlog=backlog,
            sales=sales,
            stock=stock,
            domain_product_identity_enabled=True,
            resolve_sale_code=resolve,
        ).execute(limit=1)
    row = _get_sale(sales, "kitshop:100:1")
    assert result.deducted == 1
    assert row is not None
    assert row.product_code == product.number
    assert any("kitshop_sale_resolved" in record.getMessage() for record in caplog.records)
    assert any(
        record.__dict__.get("alias_from") == "2311"
        or record.__dict__.get("extra", {}).get("alias_from") == "2311"
        for record in caplog.records
    ) or any(getattr(record, "alias_from", None) == "2311" for record in caplog.records)


def test_drain_unknown_number_does_not_insert_or_deduct() -> None:
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup(())

    def resolve(code: str):
        return resolve_kit_shop_sale_code(code, store=store, lookup=lookup)

    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="d-1001",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    result = _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        domain_product_identity_enabled=True,
        resolve_sale_code=resolve,
    ).execute(limit=1)
    assert result.deducted == 0
    assert result.held == 1
    assert _get_sale(sales, "kitshop:100:1") is None
    assert backlog._hold_reason[100] == "unknown_domain_number"


def test_drain_legacy_writes_vendor_code() -> None:
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))

    def resolve(code: str):
        return resolve_kit_shop_sale_code(code, store=store, lookup=lookup)

    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        domain_product_identity_enabled=True,
        resolve_sale_code=resolve,
    ).execute(limit=1)
    row = _get_sale(sales, "kitshop:100:1")
    assert row is not None
    assert row.product_code == "2311"
    assert row.domain_product_id == ""


def test_drain_flag_off_does_not_call_resolve() -> None:
    called = False

    def resolve(code: str) -> KitShopSaleResolve:
        nonlocal called
        called = True
        raise AssertionError(code)

    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="d-1",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        resolve_sale_code=resolve,
    ).execute(limit=1)
    assert called is False
    row = _get_sale(sales, "kitshop:100:1")
    assert row is not None
    assert row.product_code == "d-1"
    assert row.domain_product_id == ""


def test_drain_enabled_without_resolver_raises() -> None:
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="d-1",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    use_case = _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        domain_product_identity_enabled=True,
    )
    with pytest.raises(
        ValueError,
        match="domain product resolve is required when identity is enabled",
    ):
        use_case.execute(limit=1)


def test_drain_rebuilds_occupancy_and_triggers_export_once() -> None:
    from src.infrastructure.testing.company_occupancy_fakes import (
        InMemoryMachineCompanyOccupancyStore,
    )

    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    occupancy = InMemoryMachineCompanyOccupancyStore()
    calls: list[int] = []

    def _hook() -> None:
        calls.append(1)

    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    result = _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        occupancy_store=occupancy,
        after_occupancy_rebuild=_hook,
    ).execute(limit=1)
    assert result.done == 1
    intervals = occupancy.list_for_machine(MachineId("701"))
    assert len(intervals) == 1
    assert intervals[0].company_id == 7
    assert intervals[0].valid_to is None
    assert len(calls) == 1


def test_drain_skips_occupancy_rebuild_on_duplicate_insert() -> None:
    from src.infrastructure.testing.company_occupancy_fakes import (
        InMemoryMachineCompanyOccupancyStore,
    )

    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    occupancy = InMemoryMachineCompanyOccupancyStore()
    calls: list[int] = []

    def _hook() -> None:
        calls.append(1)

    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        occupancy_store=occupancy,
        after_occupancy_rebuild=_hook,
    ).execute(limit=1)
    assert len(calls) == 1

    backlog.upsert_pending(sale_id=100)
    _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        occupancy_store=occupancy,
        after_occupancy_rebuild=_hook,
    ).execute(limit=1)
    assert len(calls) == 1


def test_drain_keeps_occupancy_when_export_raises() -> None:
    from src.infrastructure.testing.company_occupancy_fakes import (
        InMemoryMachineCompanyOccupancyStore,
    )

    backlog = InMemoryKitShopSalesBacklogStore()
    backlog.upsert_pending(sale_id=100)
    sales = InMemoryMachineSalesStore()
    stock = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock)
    occupancy = InMemoryMachineCompanyOccupancyStore()

    def _boom() -> None:
        raise RuntimeError("sheets down")

    gateway = FakeKitShopSalesGateway.single_position(
        sale_id=100,
        shop_name="Офис [701]",
        vendor_code="2311",
        device_id=999,
        qty=Decimal("1"),
        kit_company_id=1,
    )
    result = _drain_uc(
        gateway=gateway,
        backlog=backlog,
        sales=sales,
        stock=stock,
        occupancy_store=occupancy,
        after_occupancy_rebuild=_boom,
    ).execute(limit=1)
    assert result.done == 1
    intervals = occupancy.list_for_machine(MachineId("701"))
    assert len(intervals) == 1
    assert intervals[0].company_id == 7
