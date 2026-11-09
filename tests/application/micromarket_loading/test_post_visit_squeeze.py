from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.micromarket_loading.assembly_orders import LaunchFromAssemblyOrders
from src.application.micromarket_loading.enqueue_post_visit_squeeze import (
    OutboxEnqueuePostVisitSqueeze,
)
from src.application.micromarket_loading.launch_loading import LaunchRejected, LoadingDisabled
from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
)
from src.application.micromarket_loading.post_visit_squeeze import (
    PostVisitSqueeze,
    PostVisitSqueezeStageFailed,
)
from src.application.micromarket_loading.shop_list_publish_journal import ShopListPublishTrigger
from src.application.outbox.micromarket_post_visit_squeeze import (
    MicromarketPostVisitSqueezeOutboxHandler,
)
from src.application.product_identity import DomainProduct
from src.domain.ids import EventId
from src.domain.micromarket_loading.assembly_order import (
    AssemblyOrderStatus,
    MicromarketAssemblyOrder,
    MicromarketAssemblyOrderLine,
)
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.domain.micromarket_loading.pending_invent import PendingMicromarketInvent
from src.domain.micromarket_loading.post_visit_squeeze_event import (
    MicromarketPostVisitSqueezeRequested,
)
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketAssemblyOrderStore,
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
    InMemoryMicromarketSalesAfter,
    InMemoryPendingMicromarketInventStore,
    InMemoryShopListPublishJournal,
)

_MACHINE = "701"
_AT = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
_TZ = ZoneInfo("Europe/Moscow")


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


class _FakeLaunch:
    def __init__(self, *, result: object | None = None) -> None:
        self.result = result
        self.calls: list[str] = []

    def execute(self, *, machine_code: str) -> object | None:
        self.calls.append(machine_code)
        return self.result


class _RecordingLaunchFromAssembly:
    def __init__(self, inner: LaunchFromAssemblyOrders) -> None:
        self._inner = inner
        self.actors: list[str] = []

    def execute(self, *, machine_code: str, actor: str = "curator") -> object | None:
        self.actors.append(actor)
        return self._inner.execute(machine_code=machine_code, actor=actor)


class _RecordingAlerter:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def send(self, text: str) -> None:
        self.messages.append(text)


class _Pub:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def _seed_stock(
    store: InMemoryMicromarketDeviceStockStore,
    *,
    qty: Decimal = Decimal("1"),
) -> None:
    stock = store.load(_MACHINE)
    if stock is None:
        from src.domain.micromarket_loading import MicromarketDeviceStock

        stock = MicromarketDeviceStock(machine_code=_MACHINE)
    stock.apply_inventory(
        as_of=_AT,
        quantities={"2311": qty},
        inventory_id="seed",
        partial=False,
    )
    store.save(stock)


def _pending(
    *,
    inventory_id: str = "inv-1",
    quantities: dict[str, Decimal] | None = None,
) -> PendingMicromarketInvent:
    qty = quantities or {"2311": Decimal("4")}
    return PendingMicromarketInvent(
        machine_code=_MACHINE,
        inventory_id=inventory_id,
        quantities=tuple(sorted(qty.items())),
        submitted_at=_AT,
        operational_day=date(2026, 11, 3),
    )


def _open_assembly(
    store: InMemoryMicromarketAssemblyOrderStore,
    *,
    catalog_code: str = "2311",
    qty: Decimal = Decimal("2"),
) -> MicromarketAssemblyOrder:
    order = MicromarketAssemblyOrder(
        order_id="asm-1",
        machine_code=_MACHINE,
        lines=(MicromarketAssemblyOrderLine(catalog_code=catalog_code, qty=qty),),
        status=AssemblyOrderStatus.OPEN,
        created_at=_AT,
    )
    store.save(order)
    return order


def _open_cycle(store: _MemoryCycleStore) -> MicromarketLoadingCycle:
    cycle = MicromarketLoadingCycle(machine_code=_MACHINE)
    cycle.save_draft(
        (
            DraftLine(
                product_code="2311",
                target_qty=0,
                stock_qty=Decimal("1"),
                need_qty=Decimal("2"),
                launch_qty=Decimal("2"),
            ),
        )
    )
    cycle.open_order(
        order_id="ord-1",
        move_id="mv-1",
        lines=cycle.lines,
        opened_at=_AT,
        timezone=_TZ,
        day_end_hour=6,
    )
    store.save(cycle)
    return cycle


def _planogram(store: InMemoryMicromarketPlanogramStore) -> None:
    store.upsert(
        MicromarketPlanogram(
            machine_code=_MACHINE,
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                    domain_product_id="prod-1",
                ),
            ),
            updated_at=_AT,
        )
    )


def _products() -> FakeDomainProductStore:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="2311",
            name="Товар",
            catalog_code="2311",
            hidden=False,
        )
    )
    return products


def _squeeze(
    *,
    pending_store: InMemoryPendingMicromarketInventStore,
    assembly: InMemoryMicromarketAssemblyOrderStore,
    launch: _FakeLaunch,
    stock_store: InMemoryMicromarketDeviceStockStore,
    alerter: _RecordingAlerter,
    cycle_store: _MemoryCycleStore | None = None,
    planogram_store: InMemoryMicromarketPlanogramStore | None = None,
    publisher: _Pub | None = None,
    journal: InMemoryShopListPublishJournal | None = None,
    products: FakeDomainProductStore | None = None,
    record_actor: bool = False,
) -> tuple[PostVisitSqueeze, _RecordingLaunchFromAssembly | None]:
    cycle = cycle_store or _MemoryCycleStore()
    inner = LaunchFromAssemblyOrders(
        assembly_store=assembly,
        cycle_store=cycle,
        warehouse_stock=None,
        launch=launch,
    )
    recording: _RecordingLaunchFromAssembly | None = None
    launch_from_assembly: LaunchFromAssemblyOrders | _RecordingLaunchFromAssembly
    if record_actor:
        recording = _RecordingLaunchFromAssembly(inner)
        launch_from_assembly = recording
    else:
        launch_from_assembly = inner
    squeeze = PostVisitSqueeze(
        pending_store=pending_store,
        launch_from_assembly=launch_from_assembly,
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        alerter=alerter,
        cycle_store=cycle_store,
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
        now_factory=lambda: _AT,
    )
    return squeeze, recording


def test_squeeze_happy_full_pipeline_load_publish_post() -> None:
    """happy: open assembly → Load(system) → one post_visit_squeeze publish → stock=pending."""
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(_pending(quantities={"2311": Decimal("4")}))
    assembly = InMemoryMicromarketAssemblyOrderStore()
    _open_assembly(assembly)
    launch = _FakeLaunch(result=None)
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock_store, qty=Decimal("1"))
    cycle_store = _MemoryCycleStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    _planogram(planogram_store)
    publisher = _Pub()
    journal = InMemoryShopListPublishJournal()
    alerter = _RecordingAlerter()

    squeeze, recording = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=launch,
        stock_store=stock_store,
        alerter=alerter,
        cycle_store=cycle_store,
        planogram_store=planogram_store,
        publisher=publisher,
        journal=journal,
        products=_products(),
        record_actor=True,
    )
    squeeze.run(machine_code=_MACHINE, inventory_id="inv-1")

    assert recording is not None
    assert recording.actors == ["system"]
    assert launch.calls == [_MACHINE]
    saved = assembly.get("asm-1")
    assert saved is not None
    assert saved.status is AssemblyOrderStatus.CONSUMED
    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], MicromarketShopListPublishRequested)
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].trigger is ShopListPublishTrigger.POST_VISIT_SQUEEZE
    stock = stock_store.load(_MACHINE)
    assert stock is not None
    assert stock.qty("2311") == Decimal("4")
    assert pending_store.get_for_machine(_MACHINE) is None
    assert alerter.messages == []


def test_squeeze_skips_load_when_no_open_assembly_session() -> None:
    """edge: empty assembly session → skip Load → publish → post."""
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(_pending(quantities={"2311": Decimal("5")}))
    assembly = InMemoryMicromarketAssemblyOrderStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock_store, qty=Decimal("1"))
    cycle_store = _MemoryCycleStore()
    _open_cycle(cycle_store)
    planogram_store = InMemoryMicromarketPlanogramStore()
    _planogram(planogram_store)
    publisher = _Pub()
    journal = InMemoryShopListPublishJournal()
    alerter = _RecordingAlerter()

    empty_launch = _FakeLaunch(result=None)
    squeeze, _ = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=empty_launch,
        stock_store=stock_store,
        alerter=alerter,
        cycle_store=cycle_store,
        planogram_store=planogram_store,
        publisher=publisher,
        journal=journal,
        products=_products(),
    )
    squeeze.run(machine_code=_MACHINE, inventory_id="inv-1")

    assert empty_launch.calls == []
    assert len(publisher.events) == 1
    assert journal.list_newest()[0].trigger is ShopListPublishTrigger.POST_VISIT_SQUEEZE
    stock = stock_store.load(_MACHINE)
    assert stock is not None
    assert stock.qty("2311") == Decimal("5")
    cycle = cycle_store.load(_MACHINE)
    assert cycle is not None
    assert cycle.status is OrderStatus.CLOSED
    assert pending_store.get_for_machine(_MACHINE) is None
    assert alerter.messages == []


def test_squeeze_load_fail_alerts_and_keeps_pending() -> None:
    """error: LaunchRejected → alert AND raise; pending remains; no apply_inventory / no publish."""
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(_pending())
    assembly = InMemoryMicromarketAssemblyOrderStore()
    _open_assembly(assembly)
    launch = _FakeLaunch(result=LaunchRejected(reason="move_failed: boom"))
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock_store, qty=Decimal("1"))
    planogram_store = InMemoryMicromarketPlanogramStore()
    _planogram(planogram_store)
    publisher = _Pub()
    alerter = _RecordingAlerter()

    squeeze, _ = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=launch,
        stock_store=stock_store,
        alerter=alerter,
        planogram_store=planogram_store,
        publisher=publisher,
        journal=InMemoryShopListPublishJournal(),
        products=_products(),
    )
    with pytest.raises(PostVisitSqueezeStageFailed):
        squeeze.run(machine_code=_MACHINE, inventory_id="inv-1")

    assert launch.calls == [_MACHINE]
    assert assembly.get("asm-1") is not None
    assert assembly.get("asm-1").status is AssemblyOrderStatus.OPEN  # type: ignore[union-attr]
    assert publisher.events == []
    assert stock_store.load(_MACHINE).qty("2311") == Decimal("1")  # type: ignore[union-attr]
    pending = pending_store.get_for_machine(_MACHINE)
    assert pending is not None
    assert pending.inventory_id == "inv-1"
    assert len(alerter.messages) == 1
    assert "stage=load" in alerter.messages[0]
    assert "LaunchRejected" in alerter.messages[0]


def test_outbox_handler_publish_fail_raises_keeps_pending_and_alerts() -> None:
    """error: publish stoppable fail → handler raises (outbox retry); pending remains; alert."""
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(_pending(quantities={"2311": Decimal("4")}))
    assembly = InMemoryMicromarketAssemblyOrderStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock_store, qty=Decimal("1"))
    planogram_store = InMemoryMicromarketPlanogramStore()
    _planogram(planogram_store)

    class _BoomPub:
        def publish(self, event: object) -> None:
            del event
            raise RuntimeError("kit unavailable")

    alerter = _RecordingAlerter()
    squeeze, _ = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=_FakeLaunch(result=None),
        stock_store=stock_store,
        alerter=alerter,
        planogram_store=planogram_store,
        publisher=_BoomPub(),  # type: ignore[arg-type]
        journal=InMemoryShopListPublishJournal(),
        products=_products(),
    )
    handler = MicromarketPostVisitSqueezeOutboxHandler(squeeze=squeeze)
    with pytest.raises(PostVisitSqueezeStageFailed):
        handler.process(
            MicromarketPostVisitSqueezeRequested(
                event_id=EventId("micromarket_post_visit_squeeze:701:inv-1"),
                machine_code=_MACHINE,
                inventory_id="inv-1",
                occurred_at=_AT,
            )
        )
    pending = pending_store.get_for_machine(_MACHINE)
    assert pending is not None
    assert pending.inventory_id == "inv-1"
    assert stock_store.load(_MACHINE).qty("2311") == Decimal("1")  # type: ignore[union-attr]
    assert len(alerter.messages) == 1
    assert "stage=publish" in alerter.messages[0]
    assert "enqueue_failed" in alerter.messages[0]


def test_squeeze_post_removes_pending_exit_line_on_explicit_zero() -> None:
    """edge: post invent clears pending_exit planogram line when pending qty is 0."""
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="2311",
            name="Товар",
            catalog_code="2311",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="prod-2",
            number="2312",
            name="Другой",
            catalog_code="2312",
            hidden=False,
        )
    )
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(
        _pending(quantities={"2311": Decimal("0"), "2312": Decimal("3")}),
    )
    assembly = InMemoryMicromarketAssemblyOrderStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    stock = stock_store.load(_MACHINE)
    if stock is None:
        from src.domain.micromarket_loading import MicromarketDeviceStock

        stock = MicromarketDeviceStock(machine_code=_MACHINE)
    stock.apply_inventory(
        as_of=_AT,
        quantities={"2311": Decimal("2"), "2312": Decimal("1")},
        inventory_id="seed",
        partial=False,
    )
    stock_store.save(stock)
    planogram_store = InMemoryMicromarketPlanogramStore()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code=_MACHINE,
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=0,
                    kit_group_id=6348,
                    domain_product_id="prod-1",
                    pending_exit=True,
                ),
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=True,
                    sort_order=1,
                    kit_group_id=6348,
                    domain_product_id="prod-2",
                    pending_exit=False,
                ),
            ),
            updated_at=_AT,
        )
    )
    publisher = _Pub()
    alerter = _RecordingAlerter()
    squeeze, _ = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=_FakeLaunch(result=None),
        stock_store=stock_store,
        alerter=alerter,
        planogram_store=planogram_store,
        publisher=publisher,
        journal=InMemoryShopListPublishJournal(),
        products=products,
    )
    squeeze.run(machine_code=_MACHINE, inventory_id="inv-1")

    doc = planogram_store.get(_MACHINE)
    assert doc is not None
    assert [line.domain_product_id for line in doc.lines] == ["prod-2"]
    assert pending_store.get_for_machine(_MACHINE) is None
    assert alerter.messages == []


def test_squeeze_loading_disabled_alerts_and_continues_publish_post() -> None:
    """edge: LoadingDisabled with open session → alert AND continue publish+post."""
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(_pending(quantities={"2311": Decimal("4")}))
    assembly = InMemoryMicromarketAssemblyOrderStore()
    _open_assembly(assembly)
    launch = _FakeLaunch(result=LoadingDisabled(message="загрузка выключена"))
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock_store)
    planogram_store = InMemoryMicromarketPlanogramStore()
    _planogram(planogram_store)
    publisher = _Pub()
    journal = InMemoryShopListPublishJournal()
    alerter = _RecordingAlerter()

    squeeze, _ = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=launch,
        stock_store=stock_store,
        alerter=alerter,
        planogram_store=planogram_store,
        publisher=publisher,
        journal=journal,
        products=_products(),
    )
    squeeze.run(machine_code=_MACHINE, inventory_id="inv-1")

    assert len(alerter.messages) == 1
    assert "LoadingDisabled" in alerter.messages[0]
    assert "stage=load" in alerter.messages[0]
    assert len(publisher.events) == 1
    assert journal.list_newest()[0].trigger is ShopListPublishTrigger.POST_VISIT_SQUEEZE
    stock = stock_store.load(_MACHINE)
    assert stock is not None
    assert stock.qty("2311") == Decimal("4")
    assert pending_store.get_for_machine(_MACHINE) is None
    assert assembly.get("asm-1").status is AssemblyOrderStatus.OPEN  # type: ignore[union-attr]


def test_squeeze_publish_skip_without_publisher_alerts_and_continues_post() -> None:
    """edge: missing publisher/planogram → alert (not silent); post still applies."""
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(_pending(quantities={"2311": Decimal("6")}))
    assembly = InMemoryMicromarketAssemblyOrderStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock_store, qty=Decimal("1"))
    alerter = _RecordingAlerter()

    squeeze, _ = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=_FakeLaunch(result=None),
        stock_store=stock_store,
        alerter=alerter,
    )
    squeeze.run(machine_code=_MACHINE, inventory_id="inv-1")

    assert len(alerter.messages) == 1
    assert "publisher_or_planogram_missing" in alerter.messages[0]
    assert "stage=publish" in alerter.messages[0]
    stock = stock_store.load(_MACHINE)
    assert stock is not None
    assert stock.qty("2311") == Decimal("6")
    assert pending_store.get_for_machine(_MACHINE) is None


def test_squeeze_pending_zeros_mark_publish_lines_disabled() -> None:
    """happy: pending zero qty → overlay factual zero → publish line disabled=True."""
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(_pending(quantities={"2311": Decimal("0")}))
    assembly = InMemoryMicromarketAssemblyOrderStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock_store, qty=Decimal("3"))
    planogram_store = InMemoryMicromarketPlanogramStore()
    _planogram(planogram_store)
    publisher = _Pub()
    journal = InMemoryShopListPublishJournal()
    alerter = _RecordingAlerter()

    squeeze, _ = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=_FakeLaunch(result=None),
        stock_store=stock_store,
        alerter=alerter,
        planogram_store=planogram_store,
        publisher=publisher,
        journal=journal,
        products=_products(),
    )
    squeeze.run(machine_code=_MACHINE, inventory_id="inv-1")

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)
    by_code = {code: disabled for code, _price, _group, disabled in event.lines}
    assert by_code["2311"] is True
    assert journal.list_newest()[0].trigger is ShopListPublishTrigger.POST_VISIT_SQUEEZE
    stock = stock_store.load(_MACHINE)
    assert stock is not None
    assert stock.qty("2311") == Decimal("0")
    assert pending_store.get_for_machine(_MACHINE) is None
    assert alerter.messages == []


def test_accept_path_outbox_enqueue_does_not_run_squeeze_sync() -> None:
    """happy: Accept enqueue publishes outbox event; does not call PostVisitSqueeze.run."""
    publisher = _Pub()
    enqueue = OutboxEnqueuePostVisitSqueeze(publisher=publisher, clock=lambda: _AT)
    enqueue.enqueue(machine_code=_MACHINE, inventory_id="inv-outbox-1")

    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, MicromarketPostVisitSqueezeRequested)
    assert event.machine_code == _MACHINE
    assert event.inventory_id == "inv-outbox-1"
    assert event.event_id.value == "micromarket_post_visit_squeeze:701:inv-outbox-1"


def test_outbox_handler_drains_to_squeeze_run() -> None:
    """happy: effects handler drains event → PostVisitSqueeze.run → post invent."""
    pending_store = InMemoryPendingMicromarketInventStore()
    pending_store.save(_pending(quantities={"2311": Decimal("7")}))
    assembly = InMemoryMicromarketAssemblyOrderStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_stock(stock_store, qty=Decimal("1"))
    planogram_store = InMemoryMicromarketPlanogramStore()
    _planogram(planogram_store)
    publisher = _Pub()
    alerter = _RecordingAlerter()
    squeeze, _ = _squeeze(
        pending_store=pending_store,
        assembly=assembly,
        launch=_FakeLaunch(result=None),
        stock_store=stock_store,
        alerter=alerter,
        planogram_store=planogram_store,
        publisher=publisher,
        journal=InMemoryShopListPublishJournal(),
        products=_products(),
    )
    handler = MicromarketPostVisitSqueezeOutboxHandler(squeeze=squeeze)
    handler.process(
        MicromarketPostVisitSqueezeRequested(
            event_id=EventId("micromarket_post_visit_squeeze:701:inv-1"),
            machine_code=_MACHINE,
            inventory_id="inv-1",
            occurred_at=_AT,
        )
    )
    stock = stock_store.load(_MACHINE)
    assert stock is not None
    assert stock.qty("2311") == Decimal("7")
    assert pending_store.get_for_machine(_MACHINE) is None


def test_post_visit_squeeze_trigger_label() -> None:
    assert ShopListPublishTrigger.POST_VISIT_SQUEEZE.label_ru == "система · пост-визитный дожим"
