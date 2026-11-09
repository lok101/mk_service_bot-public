from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.micromarket_loading.launch_loading import (
    LaunchMicromarketLoading,
    LaunchRejected,
    LoadingDisabled,
)
from src.application.micromarket_loading.move_gateway import MoveAlreadyGone, MoveDeleteFailed
from src.application.micromarket_loading.ports import MicromarketWarehouseStockSnapshotPort
from src.application.micromarket_loading.rollback_loading import (
    RollbackMicromarketLoading,
    RollbackNotAllowed,
)
from src.application.micromarket_loading.save_draft import SaveMicromarketLoadingDraft
from src.application.micromarket_loading.warehouse_stock_snapshot import (
    MainWarehouseStockSnapshot,
)
from src.application.product_identity import create_domain_product, link_domain_product
from src.application.product_identity.models import CatalogProduct
from src.application.product_identity.ports import DomainProductStore
from src.domain.micromarket_loading.aggregate import MicromarketDeviceStock
from src.domain.micromarket_loading.events import MicromarketLoadingApplied
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketWarehouseStockSnapshotStore,
)

_TZ = ZoneInfo("Europe/Moscow")
_HOUR = 6
_AT = datetime(2026, 9, 24, 10, 0, tzinfo=_TZ)


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


class _MemoryStock:
    def __init__(self) -> None:
        self.stock: MicromarketDeviceStock | None = None
        self.save_called = False

    def load(self, machine_code: str) -> MicromarketDeviceStock | None:
        return self.stock

    def save(self, stock: MicromarketDeviceStock) -> None:
        self.save_called = True
        self.stock = stock

    def list_events(self, machine_code: str) -> tuple[object, ...]:
        return ()


class _FakeGateway:
    def __init__(
        self,
        *,
        warehouse: dict[str, Decimal] | None = None,
        fail: bool = False,
        read_fail: bool = False,
        delete_mode: str = "ok",
    ) -> None:
        self.warehouse = warehouse or {}
        self.fail = fail
        self.read_fail = read_fail
        self.delete_mode = delete_mode
        self.create_calls: list[str] = []
        self.create_positions: list[tuple[tuple[str, Decimal], ...]] = []
        self.delete_calls: list[str] = []

    def warehouse_qty(self, product_code: str) -> Decimal:
        if self.read_fail:
            raise RuntimeError("warehouse unread")
        return self.warehouse.get(product_code, Decimal("0"))

    def warehouse_qty_by_codes(self, product_codes: Sequence[str]) -> dict[str, Decimal]:
        if self.read_fail:
            raise RuntimeError("warehouse unread")
        return {code: self.warehouse.get(code, Decimal("0")) for code in product_codes}

    def create_move(
        self,
        *,
        order_id: str,
        machine_code: str,
        positions: tuple[tuple[str, Decimal], ...],
    ) -> str:
        if self.fail:
            raise RuntimeError("move failed")
        self.create_calls.append(order_id)
        self.create_positions.append(positions)
        return f"move-{order_id}"

    def delete_move(self, *, move_id: str) -> None:
        self.delete_calls.append(move_id)
        if self.delete_mode == "gone":
            raise MoveAlreadyGone()
        if self.delete_mode == "fail":
            raise MoveDeleteFailed("delete failed")

    def move_moment(self, *, move_id: str) -> datetime | None:
        del move_id
        return None

    def existing_move_for_order_is_stale(
        self,
        *,
        order_id: str,
        now: datetime,
    ) -> bool:
        del now
        return order_id in getattr(self, "stale_order_ids", ())


def _line(
    *,
    product_code: str = "2311",
    launch_qty: Decimal = Decimal("2"),
) -> DraftLine:
    return DraftLine(
        product_code=product_code,
        target_qty=4,
        stock_qty=Decimal("1"),
        need_qty=Decimal("3"),
        launch_qty=launch_qty,
    )


def _seed_draft(store: _MemoryCycleStore, *lines: DraftLine) -> None:
    SaveMicromarketLoadingDraft(cycle_store=store).execute(
        machine_code="701",
        lines=lines if lines else (_line(),),
    )


def _seed_shelf(stock_store: _MemoryStock) -> MicromarketDeviceStock:
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"2311": Decimal("1")},
        inventory_id="inv-1",
    )
    stock.pull_events()
    stock_store.stock = stock
    return stock


def _launch(
    *,
    cycle_store: _MemoryCycleStore,
    stock_store: _MemoryStock,
    gateway: _FakeGateway,
    execute_enabled: bool = True,
    warehouse_gate_enabled: bool = True,
    products: DomainProductStore | None = None,
    warehouse_stock: MicromarketWarehouseStockSnapshotPort | None = None,
) -> LaunchMicromarketLoading:
    return LaunchMicromarketLoading(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        execute_enabled=execute_enabled,
        warehouse_gate_enabled=warehouse_gate_enabled,
        timezone=_TZ,
        day_end_hour=_HOUR,
        clock=lambda: _AT,
        products=products,
        warehouse_stock=warehouse_stock,
    )


_WAREHOUSE_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def _seed_warehouse_snapshot(
    *,
    qty_by_catalog_code: dict[str, Decimal],
) -> InMemoryMicromarketWarehouseStockSnapshotStore:
    store = InMemoryMicromarketWarehouseStockSnapshotStore()
    store.replace(
        MainWarehouseStockSnapshot(
            warehouse_id=_WAREHOUSE_ID,
            refreshed_at=_AT,
            qty_by_catalog_code=qty_by_catalog_code,
        ),
    )
    return store


def test_save_draft_stores_lines_without_move() -> None:
    store = _MemoryCycleStore()
    line = _line()
    SaveMicromarketLoadingDraft(cycle_store=store).execute(machine_code="701", lines=(line,))
    loaded = store.load("701")
    assert loaded is not None
    assert loaded.lines == (line,)
    assert loaded.status is None


def test_launch_leaves_shelf_unchanged() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store)
    stock = _seed_shelf(stock_store)

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
    ).execute(machine_code="701")

    assert result is None
    assert stock.qty("2311") == Decimal("1")
    assert stock_store.save_called is False
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.OPEN


def test_launch_create_move_uses_catalog_code_not_number() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    product = create_domain_product("Молоко", store=store, lookup=lookup)
    link_domain_product(product.domain_product_id, "2311", store=store, lookup=lookup)
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store, _line(product_code=product.number, launch_qty=Decimal("2")))

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        products=store,
    ).execute(machine_code="701")

    assert result is None
    assert len(gateway.create_positions) == 1
    assert gateway.create_positions[0][0][0] == "2311"
    assert gateway.create_positions[0][0][0] != product.number
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.OPEN


def test_launch_skips_line_without_catalog_code() -> None:
    store = FakeDomainProductStore()
    lookup = FakeCatalogLookup((CatalogProduct(code="2311", name="Молоко", archived=False),))
    linked = create_domain_product("Молоко", store=store, lookup=lookup)
    link_domain_product(linked.domain_product_id, "2311", store=store, lookup=lookup)
    unlinked = create_domain_product("Кефир", store=store, lookup=FakeCatalogLookup(()))
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(
        cycle_store,
        _line(product_code=linked.number, launch_qty=Decimal("2")),
        _line(product_code=unlinked.number, launch_qty=Decimal("3")),
    )

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        products=store,
    ).execute(machine_code="701")

    assert result is None
    assert len(gateway.create_positions) == 1
    assert gateway.create_positions[0] == (("2311", Decimal("2")),)


def test_launch_no_create_move_when_all_lines_lack_catalog() -> None:
    store = FakeDomainProductStore()
    product = create_domain_product("Молоко", store=store, lookup=FakeCatalogLookup(()))
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store, _line(product_code=product.number, launch_qty=Decimal("2")))

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        products=store,
    ).execute(machine_code="701")

    assert isinstance(result, LaunchRejected)
    assert result.reason == "no_catalog_positions"
    assert gateway.create_calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is not OrderStatus.OPEN


def test_launch_does_not_emit_loading_applied() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store)
    stock = _seed_shelf(stock_store)

    _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
    ).execute(machine_code="701")

    events = stock.pull_events()
    assert not any(isinstance(event, MicromarketLoadingApplied) for event in events)


def test_sale_deducts_shelf_while_order_is_open() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store)
    stock = _seed_shelf(stock_store)

    _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
    ).execute(machine_code="701")

    stock.apply_sale_deduct(
        sale_source_id="sale-1",
        product_code="2311",
        qty=Decimal("1"),
        occurred_at=_AT,
    )
    assert stock.qty("2311") == Decimal("0")
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.OPEN


def test_launch_when_execute_disabled_does_not_open_order() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store)

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        execute_enabled=False,
    ).execute(machine_code="701")

    assert isinstance(result, LoadingDisabled)
    assert result.message == "загрузка выключена"
    assert gateway.create_calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is None


def test_move_failure_does_not_open_order() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")}, fail=True)
    _seed_draft(cycle_store)

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
    ).execute(machine_code="701")

    assert isinstance(result, LaunchRejected)
    assert "move_failed" in result.reason

    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is not OrderStatus.OPEN
    assert loaded.order_id is not None


def test_launch_rejects_qty_above_fresh_warehouse() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("1")})
    _seed_draft(cycle_store, _line(launch_qty=Decimal("2")))

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
    ).execute(machine_code="701")

    assert isinstance(result, LaunchRejected)
    assert result.reason == "launch_qty_above_warehouse"
    assert gateway.create_calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is not OrderStatus.OPEN


def test_launch_allows_qty_above_warehouse_when_gate_disabled() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("1")}, read_fail=True)
    _seed_draft(cycle_store, _line(launch_qty=Decimal("2")))

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        warehouse_gate_enabled=False,
    ).execute(machine_code="701")

    assert result is None
    assert len(gateway.create_calls) == 1
    assert gateway.create_positions[0] == (("2311", Decimal("2")),)
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.OPEN


def test_launch_rejects_when_every_launch_qty_is_zero() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store, _line(launch_qty=Decimal("0")))

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
    ).execute(machine_code="701")

    assert isinstance(result, LaunchRejected)
    assert gateway.create_calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is not OrderStatus.OPEN


def test_launch_rejects_when_warehouse_read_fails() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")}, read_fail=True)
    _seed_draft(cycle_store)

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
    ).execute(machine_code="701")

    assert isinstance(result, LaunchRejected)
    assert "warehouse_read_failed" in result.reason
    assert gateway.create_calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is not OrderStatus.OPEN


def test_retry_same_order_id_does_not_create_second_move() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store)
    uc = _launch(cycle_store=cycle_store, stock_store=stock_store, gateway=gateway)

    assert uc.execute(machine_code="701") is None
    first_ids = list(gateway.create_calls)
    assert len(first_ids) == 1

    assert uc.execute(machine_code="701") is None
    assert len(set(gateway.create_calls)) == 1
    assert gateway.create_calls[0] == first_ids[0]


def test_launch_mints_fresh_order_id_when_ms_move_for_intent_is_stale() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    gateway.stale_order_ids = {"stale-order"}
    _seed_draft(cycle_store)
    cycle = cycle_store.load("701")
    assert cycle is not None
    cycle.record_launch_intent(order_id="stale-order")
    cycle_store.save(cycle)
    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
    ).execute(machine_code="701")
    assert result is None
    assert len(gateway.create_calls) == 1
    assert gateway.create_calls[0] != "stale-order"


def test_retry_after_move_failure_reuses_same_order_id() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")}, fail=True)
    _seed_draft(cycle_store)
    uc = _launch(cycle_store=cycle_store, stock_store=stock_store, gateway=gateway)
    rejected = uc.execute(machine_code="701")
    assert isinstance(rejected, LaunchRejected)
    loaded = cycle_store.load("701")
    assert loaded is not None
    order_id = loaded.order_id
    assert order_id is not None
    assert loaded.status is not OrderStatus.OPEN
    gateway.fail = False
    assert uc.execute(machine_code="701") is None
    assert gateway.create_calls == [order_id]
    opened = cycle_store.load("701")
    assert opened is not None
    assert opened.status is OrderStatus.OPEN
    assert opened.order_id == order_id


def test_launch_rejected_when_recounted_does_not_create_move() -> None:
    cycle_store = _MemoryCycleStore()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _open_order(cycle_store, gateway)
    cycle = cycle_store.load("701")
    assert cycle is not None
    original_id = cycle.order_id
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycle_store.save(cycle)
    gateway.create_calls.clear()
    result = _launch(
        cycle_store=cycle_store,
        stock_store=_MemoryStock(),
        gateway=gateway,
    ).execute(machine_code="701")
    assert isinstance(result, LaunchRejected)
    assert gateway.create_calls == []
    after = cycle_store.load("701")
    assert after is not None
    assert after.status is OrderStatus.RECOUNTED
    assert after.order_id == original_id


def test_launch_after_closed_and_draft_uses_new_order_id() -> None:
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _open_order(cycle_store, gateway)
    cycle = cycle_store.load("701")
    assert cycle is not None
    old_order_id = cycle.order_id
    assert old_order_id is not None
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycle.close(at=_AT)
    cycle_store.save(cycle)
    SaveMicromarketLoadingDraft(cycle_store=cycle_store).execute(
        machine_code="701",
        lines=(_line(),),
    )
    gateway.create_calls.clear()
    next_day = datetime(2026, 9, 25, 10, 0, tzinfo=_TZ)
    result = LaunchMicromarketLoading(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        execute_enabled=True,
        timezone=_TZ,
        day_end_hour=_HOUR,
        clock=lambda: next_day,
    ).execute(machine_code="701")
    assert result is None
    assert len(gateway.create_calls) == 1
    assert gateway.create_calls[0] != old_order_id
    opened = cycle_store.load("701")
    assert opened is not None
    assert opened.status is OrderStatus.OPEN
    assert opened.order_id == gateway.create_calls[0]


def test_launch_rejected_when_closed_same_day_does_not_create_move() -> None:
    cycle_store = _MemoryCycleStore()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _open_order(cycle_store, gateway)
    cycle = cycle_store.load("701")
    assert cycle is not None
    original_id = cycle.order_id
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycle.close(at=_AT)
    cycle_store.save(cycle)
    gateway.create_calls.clear()
    result = _launch(
        cycle_store=cycle_store,
        stock_store=_MemoryStock(),
        gateway=gateway,
    ).execute(machine_code="701")
    assert isinstance(result, LaunchRejected)
    assert gateway.create_calls == []
    after = cycle_store.load("701")
    assert after is not None
    assert after.status is OrderStatus.CLOSED
    assert after.order_id == original_id


def _open_order(
    cycle_store: _MemoryCycleStore,
    gateway: _FakeGateway,
    stock_store: _MemoryStock | None = None,
) -> None:
    stock = stock_store if stock_store is not None else _MemoryStock()
    _seed_draft(cycle_store)
    assert (
        _launch(cycle_store=cycle_store, stock_store=stock, gateway=gateway).execute(
            machine_code="701"
        )
        is None
    )


def test_rollback_from_open_removes_move_and_marks_rolled_back() -> None:
    cycle_store = _MemoryCycleStore()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _open_order(cycle_store, gateway)
    loaded = cycle_store.load("701")
    assert loaded is not None
    move_id = loaded.move_id
    assert move_id is not None

    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=gateway,
        clock=lambda: _AT,
    ).execute(machine_code="701")

    assert result is None
    assert gateway.delete_calls == [move_id]
    rolled = cycle_store.load("701")
    assert rolled is not None
    assert rolled.status is OrderStatus.ROLLED_BACK


def test_rollback_keeps_order_open_when_move_removal_fails() -> None:
    cycle_store = _MemoryCycleStore()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")}, delete_mode="fail")
    _open_order(cycle_store, gateway)
    before = cycle_store.load("701")
    assert before is not None
    move_id = before.move_id

    with pytest.raises(MoveDeleteFailed):
        RollbackMicromarketLoading(
            cycle_store=cycle_store,
            gateway=gateway,
            clock=lambda: _AT,
        ).execute(machine_code="701")

    after = cycle_store.load("701")
    assert after is not None
    assert after.status is OrderStatus.OPEN
    assert after.move_id == move_id


def test_rollback_treats_missing_move_as_removed() -> None:
    cycle_store = _MemoryCycleStore()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")}, delete_mode="gone")
    _open_order(cycle_store, gateway)

    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=gateway,
        clock=lambda: _AT,
    ).execute(machine_code="701")

    assert result is None
    rolled = cycle_store.load("701")
    assert rolled is not None
    assert rolled.status is OrderStatus.ROLLED_BACK


def test_rollback_rejected_when_recounted() -> None:
    cycle_store = _MemoryCycleStore()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _open_order(cycle_store, gateway)
    cycle = cycle_store.load("701")
    assert cycle is not None
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("-1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycle_store.save(cycle)

    result = RollbackMicromarketLoading(
        cycle_store=cycle_store,
        gateway=gateway,
        clock=lambda: _AT,
    ).execute(machine_code="701")

    assert isinstance(result, RollbackNotAllowed)
    assert gateway.delete_calls == []
    after = cycle_store.load("701")
    assert after is not None
    assert after.status is OrderStatus.RECOUNTED


class _RecordingEnsureOpen:
    def __init__(self, *, visit_id: str = "field:701:2026-09-24") -> None:
        self.visit_id = visit_id
        self.calls: list[dict[str, object]] = []

    def ensure_open(
        self,
        *,
        machine_code: str,
        at: datetime,
        source: str,
        loading_order_id: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "machine_code": machine_code,
                "at": at,
                "source": source,
                "loading_order_id": loading_order_id,
            }
        )
        return self.visit_id


def test_launch_does_not_ensure_visit_task() -> None:
    """happy: launch opens order without ensure VisitTask (ADR-0090)."""
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    ensure = _RecordingEnsureOpen(visit_id="field:701:2026-09-24")
    _seed_draft(cycle_store)
    result = LaunchMicromarketLoading(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        execute_enabled=True,
        timezone=_TZ,
        day_end_hour=_HOUR,
        clock=lambda: _AT,
        ensure_open_visit=ensure,
    ).execute(machine_code="701")
    assert result is None
    assert ensure.calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.OPEN
    assert loaded.visit_id is None


def test_launch_already_open_keeps_existing_visit_link() -> None:
    """happy: already-open launch keeps prior visit_id; no ensure."""
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    _seed_draft(cycle_store)
    first = LaunchMicromarketLoading(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        execute_enabled=True,
        timezone=_TZ,
        day_end_hour=_HOUR,
        clock=lambda: _AT,
    ).execute(machine_code="701")
    assert first is None
    opened = cycle_store.load("701")
    assert opened is not None
    opened.link_visit("scheduled:701:2026-09-24")
    cycle_store.save(opened)
    ensure = _RecordingEnsureOpen(visit_id="should-not-call")
    second = LaunchMicromarketLoading(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        execute_enabled=True,
        timezone=_TZ,
        day_end_hour=_HOUR,
        clock=lambda: _AT,
        ensure_open_visit=ensure,
    ).execute(machine_code="701")
    assert second is None
    assert ensure.calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.OPEN
    assert loaded.visit_id == "scheduled:701:2026-09-24"


def test_launch_repeat_already_open_without_ensure() -> None:
    """edge: repeat launch while open does not ensure VisitTask."""
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    ensure = _RecordingEnsureOpen(visit_id="field:701:2026-09-24")
    _seed_draft(cycle_store)
    launch = LaunchMicromarketLoading(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        execute_enabled=True,
        timezone=_TZ,
        day_end_hour=_HOUR,
        clock=lambda: _AT,
        ensure_open_visit=ensure,
    )
    assert launch.execute(machine_code="701") is None
    assert launch.execute(machine_code="701") is None
    assert ensure.calls == []
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.visit_id is None


def test_launch_disabled_skips_ensure() -> None:
    """error path: LaunchDisabled/disabled without ensure."""
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("5")})
    ensure = _RecordingEnsureOpen()
    _seed_draft(cycle_store)
    result = LaunchMicromarketLoading(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        execute_enabled=False,
        timezone=_TZ,
        day_end_hour=_HOUR,
        clock=lambda: _AT,
        ensure_open_visit=ensure,
    ).execute(machine_code="701")
    assert isinstance(result, LoadingDisabled)
    assert ensure.calls == []


def test_launch_gates_from_snapshot_and_decrements() -> None:
    """happy: gate from warehouse snapshot; after create_move apply_delta(−)."""
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("99")})
    snapshot = _seed_warehouse_snapshot(qty_by_catalog_code={"2311": Decimal("5")})
    _seed_draft(cycle_store, _line(launch_qty=Decimal("2")))

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        warehouse_stock=snapshot,
    ).execute(machine_code="701")

    assert result is None
    assert gateway.create_calls
    loaded = snapshot.get()
    assert loaded is not None
    assert loaded.qty_by_catalog_code["2311"] == Decimal("3")


def test_launch_rejects_when_snapshot_qty_insufficient() -> None:
    """error: launch_qty above snapshot warehouse qty."""
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("99")})
    snapshot = _seed_warehouse_snapshot(qty_by_catalog_code={"2311": Decimal("1")})
    _seed_draft(cycle_store, _line(launch_qty=Decimal("2")))

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        warehouse_stock=snapshot,
    ).execute(machine_code="701")

    assert isinstance(result, LaunchRejected)
    assert result.reason == "launch_qty_above_warehouse"
    assert gateway.create_calls == []
    loaded = snapshot.get()
    assert loaded is not None
    assert loaded.qty_by_catalog_code["2311"] == Decimal("1")


def test_launch_rejects_when_warehouse_snapshot_missing() -> None:
    """error: warehouse_stock port set but get() is None."""
    cycle_store = _MemoryCycleStore()
    stock_store = _MemoryStock()
    gateway = _FakeGateway(warehouse={"2311": Decimal("99")})
    snapshot = InMemoryMicromarketWarehouseStockSnapshotStore()
    _seed_draft(cycle_store)

    result = _launch(
        cycle_store=cycle_store,
        stock_store=stock_store,
        gateway=gateway,
        warehouse_stock=snapshot,
    ).execute(machine_code="701")

    assert isinstance(result, LaunchRejected)
    assert result.reason == "warehouse_snapshot_missing"
    assert gateway.create_calls == []
