from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.application.micromarket_loading.ops_accept_loading import OpsAcceptMicromarketLoading
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.domain.micromarket_loading.order_events import (
    OPS_CONFIRMED_WITHOUT_RECOUNT,
    MicromarketLoadingCycleEvent,
)
from src.infrastructure.testing.micromarket_loading_fakes import InMemoryMicromarketDeviceStockStore

_TZ = ZoneInfo("UTC")
_AT = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
_MACHINE = "701"


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


def _line(*, launch: str = "2", stock: str = "1") -> DraftLine:
    return DraftLine(
        product_code="2311",
        target_qty=4,
        stock_qty=Decimal(stock),
        need_qty=Decimal("3"),
        launch_qty=Decimal(launch),
    )


def _open_cycle(store: _MemoryCycleStore) -> MicromarketLoadingCycle:
    cycle = MicromarketLoadingCycle(machine_code=_MACHINE)
    cycle.open_order(
        order_id="order-701",
        move_id="move-701",
        lines=(_line(),),
        opened_at=_AT,
        timezone=_TZ,
        day_end_hour=4,
    )
    store.save(cycle)
    return cycle


def test_ops_accept_applies_launch_and_closes_open_order() -> None:
    cycles = _MemoryCycleStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    stock = MicromarketDeviceStock(machine_code=_MACHINE)
    stock.apply_loading(
        lines={"2311": Decimal("1")},
        loading_run_id="seed",
        occurred_at=_AT,
    )
    stock_store.save(stock)
    _open_cycle(cycles)

    result = OpsAcceptMicromarketLoading(
        cycle_store=cycles,
        stock_store=stock_store,
        now_factory=lambda: _AT,
    ).execute(machine_code=_MACHINE, actor_id="coord-1")

    assert result.status == "accepted"
    loaded = cycles.load(_MACHINE)
    assert loaded is not None
    assert loaded.status is OrderStatus.CLOSED
    assert loaded.close_kind == OPS_CONFIRMED_WITHOUT_RECOUNT
    assert stock_store.load(_MACHINE).qty("2311") == Decimal("3")


def test_ops_accept_retry_after_cycle_save_failure_does_not_double_stock() -> None:
    class _FailOnceCycleStore:
        """Persists event snapshots so a failed save leaves the previous open cycle."""

        def __init__(self) -> None:
            self._events: dict[str, tuple[MicromarketLoadingCycleEvent, ...]] = {}
            self.saves = 0

        def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
            events = self._events.get(machine_code)
            if not events:
                return None
            return MicromarketLoadingCycle.rehydrate(machine_code=machine_code, events=events)

        def save(self, cycle: MicromarketLoadingCycle) -> None:
            self.saves += 1
            pending = cycle.pull_events()
            if self.saves == 2:
                raise RuntimeError("cycle save failed")
            prior = self._events.get(cycle.machine_code, ())
            self._events[cycle.machine_code] = prior + pending

    cycles = _FailOnceCycleStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    _open_cycle(cycles)
    use_case = OpsAcceptMicromarketLoading(
        cycle_store=cycles,
        stock_store=stock_store,
        now_factory=lambda: _AT,
    )
    try:
        use_case.execute(machine_code=_MACHINE)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected cycle save to fail")

    result = use_case.execute(machine_code=_MACHINE)
    assert result.status == "accepted"
    assert stock_store.load(_MACHINE).qty("2311") == Decimal("2")
    loaded = cycles.load(_MACHINE)
    assert loaded is not None
    assert loaded.status is OrderStatus.CLOSED


def test_ops_accept_idempotent_second_call() -> None:
    cycles = _MemoryCycleStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    _open_cycle(cycles)
    uc = OpsAcceptMicromarketLoading(
        cycle_store=cycles,
        stock_store=stock_store,
        now_factory=lambda: _AT,
    )
    assert uc.execute(machine_code=_MACHINE).status == "accepted"
    first_qty = stock_store.load(_MACHINE).qty("2311")
    second = uc.execute(machine_code=_MACHINE)
    assert second.status == "idempotent"
    assert stock_store.load(_MACHINE).qty("2311") == first_qty


def test_ops_accept_rejects_recounted() -> None:
    cycles = _MemoryCycleStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle = _open_cycle(cycles)
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycles.save(cycle)

    result = OpsAcceptMicromarketLoading(
        cycle_store=cycles,
        stock_store=stock_store,
        now_factory=lambda: _AT,
    ).execute(machine_code=_MACHINE)

    assert result.status == "rejected"
    assert result.reason == "order_status_recounted"


def test_ops_accept_enqueues_loading_shelf_on_diff() -> None:
    from decimal import Decimal

    from tests.application.product_identity.fakes import FakeDomainProductStore

    from src.application.micromarket_loading.planogram import (
        MicromarketPlanogram,
        MicromarketPlanogramLine,
    )
    from src.application.micromarket_loading.shop_list_publish_journal import (
        ShopListPublishTrigger,
    )
    from src.application.product_identity import DomainProduct
    from src.infrastructure.testing.micromarket_loading_fakes import (
        InMemoryMicromarketPlanogramStore,
        InMemoryShopListPublishJournal,
    )

    class _Pub:
        def __init__(self) -> None:
            self.events: list[object] = []

        def publish(self, event: object) -> None:
            self.events.append(event)

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
    cycles = _MemoryCycleStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _Pub()
    journal = InMemoryShopListPublishJournal()
    _open_cycle(cycles)
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
                ),
            ),
            updated_at=_AT,
        )
    )
    result = OpsAcceptMicromarketLoading(
        cycle_store=cycles,
        stock_store=stock_store,
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
        now_factory=lambda: _AT,
    ).execute(machine_code=_MACHINE)
    assert result.status == "accepted"
    assert len(publisher.events) == 1
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].trigger is ShopListPublishTrigger.LOADING_SHELF


def test_ops_accept_skips_enqueue_when_published_and_no_diff() -> None:
    from decimal import Decimal

    from tests.application.product_identity.fakes import FakeDomainProductStore

    from src.application.micromarket_loading.planogram import (
        MicromarketPlanogram,
        MicromarketPlanogramLine,
    )
    from src.application.micromarket_loading.shop_list import ShopListPublishStatus
    from src.application.micromarket_loading.shop_list_publish_journal import (
        ShopListIntendedLine,
        ShopListLastSucceededSnapshot,
    )
    from src.application.product_identity import DomainProduct
    from src.infrastructure.testing.micromarket_loading_fakes import (
        InMemoryMicromarketPlanogramStore,
        InMemoryShopListLastSucceededSnapshotStore,
        InMemoryShopListPublishJournal,
    )

    class _Pub:
        def __init__(self) -> None:
            self.events: list[object] = []

        def publish(self, event: object) -> None:
            self.events.append(event)

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
    cycles = _MemoryCycleStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _Pub()
    journal = InMemoryShopListPublishJournal()
    baseline = InMemoryShopListLastSucceededSnapshotStore()
    baseline.upsert(
        ShopListLastSucceededSnapshot(
            machine_code=_MACHINE,
            lines=(ShopListIntendedLine("2311", Decimal("10"), 6348, False),),
            updated_at=_AT,
        )
    )
    _open_cycle(cycles)
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
                ),
            ),
            updated_at=_AT,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
        )
    )
    result = OpsAcceptMicromarketLoading(
        cycle_store=cycles,
        stock_store=stock_store,
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
        baseline_store=baseline,
        now_factory=lambda: _AT,
    ).execute(machine_code=_MACHINE)
    assert result.status == "accepted"
    assert publisher.events == []
    assert journal.list_newest() == ()


def test_ops_accept_idempotent_does_not_enqueue_again() -> None:
    from decimal import Decimal

    from tests.application.product_identity.fakes import FakeDomainProductStore

    from src.application.micromarket_loading.planogram import (
        MicromarketPlanogram,
        MicromarketPlanogramLine,
    )
    from src.application.product_identity import DomainProduct
    from src.infrastructure.testing.micromarket_loading_fakes import (
        InMemoryMicromarketPlanogramStore,
        InMemoryShopListPublishJournal,
    )

    class _Pub:
        def __init__(self) -> None:
            self.events: list[object] = []

        def publish(self, event: object) -> None:
            self.events.append(event)

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
    cycles = _MemoryCycleStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _Pub()
    journal = InMemoryShopListPublishJournal()
    _open_cycle(cycles)
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
                ),
            ),
            updated_at=_AT,
        )
    )
    uc = OpsAcceptMicromarketLoading(
        cycle_store=cycles,
        stock_store=stock_store,
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
        now_factory=lambda: _AT,
    )
    assert uc.execute(machine_code=_MACHINE).status == "accepted"
    first = len(publisher.events)
    assert uc.execute(machine_code=_MACHINE).status == "idempotent"
    assert len(publisher.events) == first
