from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from tests.application.product_identity.fakes import FakeCatalogLookup, FakeDomainProductStore

from src.application.micromarket_loading import AcceptMicromarketInventory
from src.application.micromarket_loading.accept_inventory import (
    VisitFinalizedRecountRejected,
)
from src.application.micromarket_loading.enqueue_post_visit_squeeze import (
    InMemoryEnqueuePostVisitSqueeze,
)
from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
)
from src.application.micromarket_loading.shop_list_publish_journal import (
    ShopListIntendedLine,
    ShopListLastSucceededSnapshot,
    ShopListPublishJournalStatus,
    ShopListPublishTrigger,
)
from src.application.product_identity import DomainProduct, create_domain_product
from src.domain.micromarket_loading import MicromarketDeviceStock, MicromarketStockConcurrencyError
from src.domain.micromarket_loading.events import MicromarketInventoryAccepted
from src.domain.micromarket_loading.order import DraftLine, MicromarketLoadingCycle, OrderStatus
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
    InMemoryMicromarketSalesAfter,
    InMemoryPendingMicromarketInventStore,
    InMemoryShopListLastSucceededSnapshotStore,
    InMemoryShopListPublishJournal,
)

_TZ = ZoneInfo("Europe/Moscow")
_AT = datetime(2026, 9, 24, 10, 0, tzinfo=_TZ)
_DAY_END = 6


class _MemoryCycleStore:
    def __init__(self) -> None:
        self.cycles: dict[str, MicromarketLoadingCycle] = {}

    def load(self, machine_code: str) -> MicromarketLoadingCycle | None:
        return self.cycles.get(machine_code)

    def save(self, cycle: MicromarketLoadingCycle) -> None:
        self.cycles[cycle.machine_code] = cycle


class _RecordingCompleteOpen:
    def __init__(self, *, visit_id: str = "scheduled:701:2026-09-24") -> None:
        self.visit_id = visit_id
        self.calls: list[dict[str, object]] = []

    def complete_open(
        self,
        *,
        machine_code: str,
        at: datetime,
        source: str,
    ) -> str | None:
        self.calls.append({"machine_code": machine_code, "at": at, "source": source})
        return self.visit_id


def _accept_now(
    *,
    stock_store: InMemoryMicromarketDeviceStockStore | None = None,
    sales_after: InMemoryMicromarketSalesAfter | None = None,
    cycle_store: _MemoryCycleStore | None = None,
    pending_store: InMemoryPendingMicromarketInventStore | None = None,
    ensure_open_visit: object | None = None,
    complete_open_visit: object | None = None,
    enqueue_squeeze: InMemoryEnqueuePostVisitSqueeze | None = None,
    visit_finalized: object | None = None,
    planogram_store: object | None = None,
    publisher: object | None = None,
    products: object | None = None,
    journal: object | None = None,
    baseline_store: object | None = None,
) -> AcceptMicromarketInventory:
    return AcceptMicromarketInventory(
        stock_store=stock_store or InMemoryMicromarketDeviceStockStore(),
        sales_after=sales_after or InMemoryMicromarketSalesAfter([]),
        cycle_store=cycle_store,
        planogram_store=planogram_store,  # type: ignore[arg-type]
        publisher=publisher,
        products=products,  # type: ignore[arg-type]
        journal=journal,  # type: ignore[arg-type]
        baseline_store=baseline_store,  # type: ignore[arg-type]
        visit_finalized=visit_finalized,  # type: ignore[arg-type]
        ensure_open_visit=ensure_open_visit,  # type: ignore[arg-type]
        complete_open_visit=complete_open_visit,  # type: ignore[arg-type]
        enqueue_squeeze=enqueue_squeeze or InMemoryEnqueuePostVisitSqueeze(),
        pending_store=pending_store or InMemoryPendingMicromarketInventStore(),
        timezone=_TZ,
        day_end_hour=_DAY_END,
    )


def _draft_line(
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


def _open_cycle(
    store: _MemoryCycleStore,
    *,
    machine_code: str = "701",
    lines: tuple[DraftLine, ...] | None = None,
) -> MicromarketLoadingCycle:
    cycle = MicromarketLoadingCycle(machine_code=machine_code)
    cycle.open_order(
        order_id=f"order-{machine_code}",
        move_id=f"move-{machine_code}",
        lines=lines if lines is not None else (_draft_line(),),
        opened_at=_AT,
        timezone=_TZ,
        day_end_hour=6,
    )
    store.save(cycle)
    return cycle


def _seed_shelf(
    store: InMemoryMicromarketDeviceStockStore,
    *,
    machine_code: str,
    qty: Decimal,
    inventory_id: str,
) -> None:
    stock = MicromarketDeviceStock(machine_code=machine_code)
    stock.apply_inventory(
        as_of=_AT,
        quantities={"2311": qty},
        inventory_id=inventory_id,
    )
    store.save(stock)


class _ConflictOnceStore(InMemoryMicromarketDeviceStockStore):
    def __init__(self) -> None:
        super().__init__()
        self._fails = 1

    def save(self, stock: MicromarketDeviceStock) -> None:
        if self._fails > 0:
            self._fails -= 1
            raise MicromarketStockConcurrencyError(machine_code=stock.machine_code)
        super().save(stock)


def test_accept_micromarket_inventory_retries_on_stock_conflict() -> None:
    # error then happy (as_of still applies stock)
    store = _ConflictOnceStore()
    submitted = datetime(2026, 9, 3, 10, 30, tzinfo=UTC)
    uc = AcceptMicromarketInventory(
        stock_store=store,
        sales_after=InMemoryMicromarketSalesAfter([]),
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-retry-1",
        submitted_at=submitted,
        as_of_from_form=submitted,
    )
    stock = store.load("701")
    assert stock is not None
    assert stock.qty("2311") == Decimal("4")


def test_accept_micromarket_inventory_retry_idempotent_by_inventory_id() -> None:
    # error→happy: stream already has inventory_id; OCC retry must not duplicate it
    store = _ConflictOnceStore()
    store._fails = 0
    submitted = datetime(2026, 9, 3, 10, 30, tzinfo=UTC)
    seed = MicromarketDeviceStock(machine_code="701")
    seed.apply_inventory(
        as_of=submitted,
        quantities={"2311": Decimal("4")},
        inventory_id="inv-idem-1",
    )
    store.save(seed)
    store._fails = 1
    t_sale = datetime(2026, 9, 3, 11, 0, tzinfo=UTC)
    uc = AcceptMicromarketInventory(
        stock_store=store,
        sales_after=InMemoryMicromarketSalesAfter(
            [("sale-after", "2311", Decimal("1"), t_sale)],
        ),
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-idem-1",
        submitted_at=submitted,
        as_of_from_form=submitted,
    )
    events = store.list_events("701")
    inventory_events = [e for e in events if isinstance(e, MicromarketInventoryAccepted)]
    assert len(inventory_events) == 1
    assert inventory_events[0].inventory_id == "inv-idem-1"
    stock = store.load("701")
    assert stock is not None
    assert stock.qty("2311") == Decimal("3")


def test_accept_now_persists_pending_without_stock_apply() -> None:
    """happy: Accept now → pending + enqueue; stock unchanged."""
    store = InMemoryMicromarketDeviceStockStore()
    _seed_shelf(store, machine_code="701", qty=Decimal("1"), inventory_id="seed")
    pending_store = InMemoryPendingMicromarketInventStore()
    enqueue = InMemoryEnqueuePostVisitSqueeze()
    complete = _RecordingCompleteOpen()
    ensure = _RecordingEnsureOpen()
    uc = _accept_now(
        stock_store=store,
        pending_store=pending_store,
        enqueue_squeeze=enqueue,
        complete_open_visit=complete,
        ensure_open_visit=ensure,
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-now-1",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    stock = store.load("701")
    assert stock is not None
    assert stock.qty("2311") == Decimal("1")
    pending = pending_store.get_for_machine("701")
    assert pending is not None
    assert pending.inventory_id == "inv-now-1"
    assert pending.quantity_map()["2311"] == Decimal("4")
    assert enqueue.calls == [("701", "inv-now-1")]
    assert len(ensure.calls) == 1
    assert ensure.calls[0]["source"] == "field_activity"
    assert complete.calls == []


def test_accept_now_enqueues_squeeze_without_complete_open() -> None:
    """happy: enqueue squeeze; VisitTask stays open (ADR-0096)."""
    sequence: list[str] = []

    class _OrderedComplete(_RecordingCompleteOpen):
        def complete_open(
            self,
            *,
            machine_code: str,
            at: datetime,
            source: str,
        ) -> str | None:
            sequence.append("complete")
            return super().complete_open(machine_code=machine_code, at=at, source=source)

    class _OrderedEnqueue(InMemoryEnqueuePostVisitSqueeze):
        def enqueue(self, *, machine_code: str, inventory_id: str) -> None:
            sequence.append("enqueue")
            super().enqueue(machine_code=machine_code, inventory_id=inventory_id)

    complete = _OrderedComplete()
    uc = _accept_now(
        pending_store=InMemoryPendingMicromarketInventStore(),
        enqueue_squeeze=_OrderedEnqueue(),
        complete_open_visit=complete,
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-order-1",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    assert sequence == ["enqueue"]
    assert complete.calls == []


def test_inventory_as_of_replays_sales_after_anchor() -> None:
    store = InMemoryMicromarketDeviceStockStore()
    t0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    t1 = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    sales = InMemoryMicromarketSalesAfter(
        [
            ("sale-after", "2311", Decimal("2"), t1),
        ]
    )
    uc = AcceptMicromarketInventory(stock_store=store, sales_after=sales)
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"2311": Decimal("10")},
        inventory_id="inv-asof-1",
        submitted_at=datetime(2026, 9, 2, tzinfo=UTC),
        as_of_from_form=t0,
    )
    stock = store.load("701")
    assert stock is not None
    assert stock.qty("2311") == Decimal("8")


def test_accept_sets_has_completed_inventory() -> None:
    store = InMemoryMicromarketDeviceStockStore()
    submitted = datetime(2026, 9, 3, tzinfo=UTC)
    uc = AcceptMicromarketInventory(
        stock_store=store,
        sales_after=InMemoryMicromarketSalesAfter([]),
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"2311": Decimal("0")},
        inventory_id="inv-1",
        submitted_at=submitted,
        as_of_from_form=submitted,
    )
    assert store.load("701").has_completed_inventory is True


def test_accept_now_with_open_cycle_keeps_order_and_stock() -> None:
    """happy: Accept now with OPEN cycle → pending; stock/order untouched (post deferred)."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle_store = _MemoryCycleStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    enqueue = InMemoryEnqueuePostVisitSqueeze()
    _seed_shelf(stock_store, machine_code="701", qty=Decimal("1"), inventory_id="seed-701")
    _open_cycle(cycle_store, machine_code="701")
    uc = _accept_now(
        stock_store=stock_store,
        cycle_store=cycle_store,
        pending_store=pending_store,
        enqueue_squeeze=enqueue,
        complete_open_visit=_RecordingCompleteOpen(),
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-recount-1",
        submitted_at=_AT,
        as_of_from_form=None,
        performed_technician_id="tech-perf",
        performed_technician_name="Perf",
        assigned_technician_id="tech-asg",
        assigned_technician_name="Asg",
    )
    stock = stock_store.load("701")
    assert stock is not None
    assert stock.qty("2311") == Decimal("1")
    cycle = cycle_store.load("701")
    assert cycle is not None
    assert cycle.status is OrderStatus.OPEN
    pending = pending_store.get_for_machine("701")
    assert pending is not None
    assert pending.inventory_id == "inv-recount-1"
    assert pending.performed_technician_id == "tech-perf"
    assert enqueue.calls == [("701", "inv-recount-1")]


def test_second_now_after_pending_rejected() -> None:
    """error: second Accept now after pending invent → reject; VisitTask not required."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    enqueue = InMemoryEnqueuePostVisitSqueeze()
    complete = _RecordingCompleteOpen()
    uc = _accept_now(
        stock_store=stock_store,
        pending_store=pending_store,
        enqueue_squeeze=enqueue,
        complete_open_visit=complete,
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-first",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    with pytest.raises(VisitFinalizedRecountRejected):
        uc.execute(
            mode="now",
            machine_code="701",
            quantities={"2311": Decimal("9")},
            inventory_id="inv-second",
            submitted_at=_AT,
            as_of_from_form=None,
        )
    pending = pending_store.get_for_machine("701")
    assert pending is not None
    assert pending.inventory_id == "inv-first"
    assert enqueue.calls == [("701", "inv-first")]
    assert complete.calls == []


def test_no_order_second_now_rejected_after_pending() -> None:
    """happy/error: without order, first now freezes day via pending; second rejected."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    complete = _RecordingCompleteOpen()
    uc = _accept_now(
        stock_store=stock_store,
        pending_store=pending_store,
        complete_open_visit=complete,
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-1",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    with pytest.raises(VisitFinalizedRecountRejected):
        uc.execute(
            mode="now",
            machine_code="701",
            quantities={"2311": Decimal("7")},
            inventory_id="inv-2",
            submitted_at=_AT,
            as_of_from_form=None,
        )
    assert stock_store.load("701") is None
    assert pending_store.get_for_machine("701") is not None


class _FinalizedAlways:
    def is_finalized(self, machine_code: str, checked_at: datetime) -> bool:
        return True


class _FinalizedNever:
    def is_finalized(self, machine_code: str, checked_at: datetime) -> bool:
        return False


def test_accept_now_does_not_apply_sale_side_effects_on_stock() -> None:
    """edge: Accept now leaves stock untouched (sales replay deferred to post)."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle_store = _MemoryCycleStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    _seed_shelf(stock_store, machine_code="701", qty=Decimal("1"), inventory_id="seed-701")
    _open_cycle(cycle_store, machine_code="701")
    uc = _accept_now(
        stock_store=stock_store,
        cycle_store=cycle_store,
        pending_store=pending_store,
        visit_finalized=_FinalizedNever(),
        complete_open_visit=_RecordingCompleteOpen(),
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-first",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    assert stock_store.load("701").qty("2311") == Decimal("1")
    assert cycle_store.load("701").status is OrderStatus.OPEN
    assert pending_store.get_for_machine("701") is not None


def test_visit_finalized_rejects_before_stock_write() -> None:
    """error: finalized → VisitFinalizedRecountRejected; stock/pending unchanged."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    _seed_shelf(stock_store, machine_code="701", qty=Decimal("1"), inventory_id="seed-701")
    uc = _accept_now(
        stock_store=stock_store,
        pending_store=pending_store,
        visit_finalized=_FinalizedAlways(),
    )
    with pytest.raises(VisitFinalizedRecountRejected):
        uc.execute(
            mode="now",
            machine_code="701",
            quantities={"2311": Decimal("9")},
            inventory_id="inv-blocked",
            submitted_at=_AT,
            as_of_from_form=None,
        )
    stock = stock_store.load("701")
    assert stock is not None
    assert stock.qty("2311") == Decimal("1")
    assert pending_store.get_for_machine("701") is None


def test_recounted_cycle_accept_now_keeps_stock_and_saves_pending() -> None:
    """edge: RECOUNTED cycle on Accept now → pending; no stock apply / no replace."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle_store = _MemoryCycleStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    _seed_shelf(stock_store, machine_code="701", qty=Decimal("4"), inventory_id="seed-701")
    cycle = _open_cycle(cycle_store, machine_code="701")
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycle_store.save(cycle)
    uc = _accept_now(
        stock_store=stock_store,
        cycle_store=cycle_store,
        pending_store=pending_store,
        complete_open_visit=_RecordingCompleteOpen(),
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("9")},
        inventory_id="inv-legacy",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    assert stock_store.load("701").qty("2311") == Decimal("4")
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.RECOUNTED
    assert loaded.deltas == (("2311", Decimal("1")),)
    assert pending_store.get_for_machine("701") is not None


def test_accept_now_partial_snapshot_does_not_mutate_stock() -> None:
    """happy: Accept now with partial quantities map leaves shelf basis untouched."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle_store = _MemoryCycleStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"2311": Decimal("1"), "2312": Decimal("5")},
        inventory_id="seed-both",
        partial=True,
    )
    stock_store.save(stock)
    _open_cycle(
        cycle_store,
        machine_code="701",
        lines=(
            _draft_line(product_code="2311", launch_qty=Decimal("2")),
            _draft_line(product_code="2312", launch_qty=Decimal("1")),
        ),
    )
    uc = _accept_now(
        stock_store=stock_store,
        cycle_store=cycle_store,
        pending_store=pending_store,
        complete_open_visit=_RecordingCompleteOpen(),
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-omit-launch",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    loaded = stock_store.load("701")
    assert loaded is not None
    assert loaded.qty("2311") == Decimal("1")
    assert loaded.qty("2312") == Decimal("5")
    assert cycle_store.load("701").status is OrderStatus.OPEN
    pending = pending_store.get_for_machine("701")
    assert pending is not None
    assert pending.quantity_map() == {"2311": Decimal("4")}


def test_accept_partial_false_full_replace_drops_codes_outside_map() -> None:
    """happy: partial=False replaces stock with quantities map (FieldForm full snapshot)."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"2311": Decimal("1"), "2312": Decimal("5")},
        inventory_id="seed-both",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"2311": Decimal("4")},
        inventory_id="inv-full-snapshot",
        submitted_at=_AT,
        as_of_from_form=_AT,
        partial=False,
    )
    loaded = stock_store.load("701")
    assert loaded is not None
    assert loaded.qty("2311") == Decimal("4")
    assert loaded.quantity_basis("2311") == "factual"
    assert "2312" not in loaded.quantities()
    anomalies = [
        e
        for e in stock_store.list_events("701")
        if getattr(e, "kind", None) == "inventory_line_omitted"
    ]
    assert anomalies == []


def test_accept_partial_omit_does_not_clear_last_factual_zero() -> None:
    stock_store = InMemoryMicromarketDeviceStockStore()
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"2311": Decimal("0"), "2312": Decimal("3")},
        inventory_id="seed-zero",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"2312": Decimal("2")},
        inventory_id="inv-omit-zero",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    loaded = stock_store.load("701")
    assert loaded is not None
    assert loaded.qty("2311") == Decimal("0")
    assert loaded.last_factual_qty("2311") == Decimal("0")
    assert loaded.quantity_basis("2311") == "virtual"
    assert loaded.qty("2312") == Decimal("2")
    assert loaded.quantity_basis("2312") == "factual"
    omitted_zero = [
        e
        for e in stock_store.list_events("701")
        if getattr(e, "kind", None) == "inventory_line_omitted" and e.product_code == "2311"
    ]
    assert omitted_zero == []


def test_as_of_inventory_does_not_change_order() -> None:
    # edge: as_of updates shelf, order stays open
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle_store = _MemoryCycleStore()
    _seed_shelf(stock_store, machine_code="701", qty=Decimal("1"), inventory_id="seed-701")
    _open_cycle(cycle_store, machine_code="701")
    as_of = datetime(2026, 9, 23, 12, 0, tzinfo=_TZ)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        cycle_store=cycle_store,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"2311": Decimal("10")},
        inventory_id="inv-asof-order",
        submitted_at=_AT,
        as_of_from_form=as_of,
    )
    stock = stock_store.load("701")
    assert stock is not None
    assert stock.qty("2311") == Decimal("10")
    cycle = cycle_store.load("701")
    assert cycle is not None
    assert cycle.status is OrderStatus.OPEN


def test_accept_now_allows_empty_assigned_technician() -> None:
    """happy: empty assigned technician still persists pending."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle_store = _MemoryCycleStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    _seed_shelf(stock_store, machine_code="701", qty=Decimal("1"), inventory_id="seed")
    _open_cycle(cycle_store, machine_code="701")
    uc = _accept_now(
        stock_store=stock_store,
        cycle_store=cycle_store,
        pending_store=pending_store,
        complete_open_visit=_RecordingCompleteOpen(),
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("3")},
        inventory_id="inv-empty-asg",
        submitted_at=_AT,
        as_of_from_form=None,
        performed_technician_id="tech-1",
        performed_technician_name="One",
        assigned_technician_id="",
        assigned_technician_name="",
    )
    pending = pending_store.get_for_machine("701")
    assert pending is not None
    assert pending.assigned_technician_id == ""
    assert cycle_store.load("701").status is OrderStatus.OPEN


def test_now_after_closed_order_still_saves_pending() -> None:
    """edge: CLOSED cycle → pending saved; cycle untouched."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    cycle_store = _MemoryCycleStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    _seed_shelf(stock_store, machine_code="701", qty=Decimal("2"), inventory_id="seed")
    cycle = _open_cycle(cycle_store, machine_code="701")
    cycle.mark_recounted(
        at=_AT,
        deltas=(),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycle.close(at=_AT)
    cycle_store.save(cycle)
    uc = _accept_now(
        stock_store=stock_store,
        cycle_store=cycle_store,
        pending_store=pending_store,
        complete_open_visit=_RecordingCompleteOpen(),
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("5")},
        inventory_id="inv-after-closed",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    assert stock_store.load("701").qty("2311") == Decimal("2")
    assert cycle_store.load("701").status is OrderStatus.CLOSED
    assert pending_store.get_for_machine("701") is not None


class _AcceptPublisher:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def _planogram_line(
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
        pending_exit=pending_exit,
        domain_product_id=domain_product_id,
    )


def _domain_products_n1_n2() -> FakeDomainProductStore:
    products = FakeDomainProductStore()
    products.insert(
        DomainProduct(
            domain_product_id="prod-1",
            number="n-1",
            name="Товар 1",
            catalog_code="2311",
            hidden=False,
        )
    )
    products.insert(
        DomainProduct(
            domain_product_id="prod-2",
            number="n-2",
            name="Товар 2",
            catalog_code="2312",
            hidden=False,
        )
    )
    return products


def test_accept_explicit_zero_with_pending_exit_removes_line_and_enqueues_publish() -> None:
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    journal = InMemoryShopListPublishJournal()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _planogram_line(
                    "",
                    pending_exit=True,
                    sort_order=0,
                    domain_product_id="prod-1",
                ),
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=1,
                    domain_product_id="prod-2",
                ),
            ),
            updated_at=_AT,
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"n-1": Decimal("2"), "n-2": Decimal("1")},
        inventory_id="seed-pe",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"n-1": Decimal("0"), "n-2": Decimal("1")},
        inventory_id="inv-pe-zero",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    loaded = stock_store.load("701")
    assert loaded is not None
    assert loaded.last_factual_qty("n-1") == Decimal("0")
    doc = planogram_store.get("701")
    assert doc is not None
    assert [line.domain_product_id for line in doc.lines] == ["prod-2"]
    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], MicromarketShopListPublishRequested)
    codes = [code for code, _price, _group, _disabled in publisher.events[0].lines]
    assert codes == ["n-2"]
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].trigger is ShopListPublishTrigger.PENDING_EXIT


def test_accept_explicit_zero_without_pending_exit_keeps_line_and_enqueues_publish() -> None:
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=0,
                    domain_product_id="prod-1",
                ),
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=1,
                    domain_product_id="prod-2",
                ),
            ),
            updated_at=_AT,
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"n-1": Decimal("2"), "n-2": Decimal("1")},
        inventory_id="seed-keep",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"n-1": Decimal("0"), "n-2": Decimal("1")},
        inventory_id="inv-zero-keep",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    doc = planogram_store.get("701")
    assert doc is not None
    assert [line.domain_product_id for line in doc.lines] == ["prod-1", "prod-2"]
    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], MicromarketShopListPublishRequested)
    by_code = {code: disabled for code, _price, _group, disabled in publisher.events[0].lines}
    assert by_code["n-1"] is True
    assert by_code["n-2"] is False


def test_accept_explicit_zero_enqueues_only_once_with_pending_exit_removal() -> None:
    """Удаление серой + явный нуль → всё ещё один publish event (не два)."""
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _planogram_line(
                    "",
                    pending_exit=True,
                    sort_order=0,
                    domain_product_id="prod-1",
                ),
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=1,
                    domain_product_id="prod-2",
                ),
            ),
            updated_at=_AT,
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"n-1": Decimal("2"), "n-2": Decimal("1")},
        inventory_id="seed-once",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"n-1": Decimal("0"), "n-2": Decimal("1")},
        inventory_id="inv-once",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    assert [line.domain_product_id for line in planogram_store.get("701").lines] == ["prod-2"]
    assert len(publisher.events) == 1


def test_accept_removes_pending_exit_line_without_publisher() -> None:
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _planogram_line(
                    "",
                    pending_exit=True,
                    domain_product_id="prod-1",
                ),
            ),
            updated_at=_AT,
        )
    )
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        publisher=None,
        products=products,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"n-1": Decimal("0")},
        inventory_id="inv-nopub",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    doc = planogram_store.get("701")
    assert doc is not None
    assert doc.lines == ()


def test_accept_writes_factual_qty_by_domain_number() -> None:
    store = FakeDomainProductStore()
    product = create_domain_product("Молоко", store=store, lookup=FakeCatalogLookup(()))
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    cycle_store = _MemoryCycleStore()
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        planogram_store=planogram_store,
        cycle_store=cycle_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        products=store,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={product.number: Decimal("3")},
        inventory_id="inv-number-1",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    stock = stock_store.load("701")
    assert stock is not None
    assert stock.qty(product.number) == Decimal("3")
    assert stock.last_factual_qty(product.number) == Decimal("3")


def test_accept_explicit_zero_domain_line_enqueues_filtered_publish() -> None:
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=0,
                    domain_product_id="prod-1",
                ),
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=1,
                    domain_product_id="prod-2",
                ),
            ),
            updated_at=_AT,
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"n-1": Decimal("2"), "n-2": Decimal("1")},
        inventory_id="seed-domain",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"n-1": Decimal("0"), "n-2": Decimal("1")},
        inventory_id="inv-domain-zero",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], MicromarketShopListPublishRequested)
    by_code = {code: disabled for code, _price, _group, disabled in publisher.events[0].lines}
    assert by_code["n-1"] is True
    assert by_code["n-2"] is False


def test_accept_explicit_zero_pending_exit_removes_domain_number_line() -> None:
    store = FakeDomainProductStore()
    product = create_domain_product("Молоко", store=store, lookup=FakeCatalogLookup(()))
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=False,
                    sort_order=0,
                    kit_group_id=6348,
                    pending_exit=True,
                    domain_product_id=product.domain_product_id,
                ),
            ),
            updated_at=_AT,
        )
    )
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        products=store,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={product.number: Decimal("0")},
        inventory_id="inv-exit-number",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    doc = planogram_store.get("701")
    assert doc is not None
    assert doc.lines == ()


def test_accept_explicit_zero_pending_exit_prefers_number_over_catalog() -> None:
    store = FakeDomainProductStore()
    store.insert(
        DomainProduct(
            domain_product_id="prod-exit-1",
            number="d-exit-1",
            name="Молоко с карточкой",
            catalog_code="2311",
            hidden=False,
        )
    )
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                MicromarketPlanogramLine(
                    product_code="",
                    target_qty=1,
                    price_rub=Decimal("10"),
                    active=False,
                    sort_order=0,
                    kit_group_id=6348,
                    pending_exit=True,
                    domain_product_id="prod-exit-1",
                ),
            ),
            updated_at=_AT,
        )
    )
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        products=store,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"d-exit-1": Decimal("0")},
        inventory_id="inv-exit-catalog",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    doc = planogram_store.get("701")
    assert doc is not None
    assert doc.lines == ()


def test_accept_explicit_zero_writes_journal_inventory_zero() -> None:
    # happy: inventory_zero enqueue → journal inventory_zero + disabled/running
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    journal = InMemoryShopListPublishJournal()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=0,
                    domain_product_id="prod-1",
                ),
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=1,
                    domain_product_id="prod-2",
                ),
            ),
            updated_at=_AT,
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"n-1": Decimal("2"), "n-2": Decimal("1")},
        inventory_id="seed-jz",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"n-1": Decimal("0"), "n-2": Decimal("1")},
        inventory_id="inv-jz",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].trigger is ShopListPublishTrigger.INVENTORY_ZERO
    assert rows[0].status is ShopListPublishJournalStatus.RUNNING
    assert "n-1" in rows[0].effects.disabled_product_codes


def test_accept_restore_after_factual_zero_enqueues_publish() -> None:
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    journal = InMemoryShopListPublishJournal()
    baseline = InMemoryShopListLastSucceededSnapshotStore()
    baseline.upsert(
        ShopListLastSucceededSnapshot(
            machine_code="701",
            lines=(ShopListIntendedLine("n-1", Decimal("10"), 6348, True),),
            updated_at=_AT,
        )
    )
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=0,
                    domain_product_id="prod-1",
                ),
            ),
            updated_at=_AT,
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"n-1": Decimal("0")},
        inventory_id="seed-restore",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
        baseline_store=baseline,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"n-1": Decimal("5")},
        inventory_id="inv-restore",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    assert len(publisher.events) == 1
    assert publisher.events[0].lines == (("n-1", "10", 6348, False),)
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].trigger is ShopListPublishTrigger.INVENTORY_RESTORE
    assert "n-1" in rows[0].effects.enabled_product_codes


def test_accept_recount_without_availability_boundary_does_not_enqueue() -> None:
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(
                _planogram_line(
                    "",
                    pending_exit=False,
                    sort_order=0,
                    domain_product_id="prod-1",
                ),
            ),
            updated_at=_AT,
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"n-1": Decimal("5")},
        inventory_id="seed-recount",
        partial=True,
    )
    stock_store.save(stock)
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
    )
    uc.execute(
        mode="as_of",
        machine_code="701",
        quantities={"n-1": Decimal("3")},
        inventory_id="inv-recount",
        submitted_at=_AT,
        as_of_from_form=_AT,
    )
    assert publisher.events == []


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


def test_accept_now_lazy_ensures_without_completing_visit() -> None:
    """happy: lazy now without order → ensure field_activity; VisitTask stays open."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    ensure = _RecordingEnsureOpen(visit_id="field:701:2026-09-24")
    complete = _RecordingCompleteOpen(visit_id="field:701:2026-09-24")
    pending_store = InMemoryPendingMicromarketInventStore()
    uc = _accept_now(
        stock_store=stock_store,
        pending_store=pending_store,
        ensure_open_visit=ensure,
        complete_open_visit=complete,
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("2")},
        inventory_id="inv-lazy",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    assert len(ensure.calls) == 1
    assert ensure.calls[0]["source"] == "field_activity"
    assert ensure.calls[0]["loading_order_id"] is None
    assert complete.calls == []
    assert stock_store.load("701") is None
    assert pending_store.get_for_machine("701") is not None


def test_accept_now_after_closed_order_does_not_relink_visit() -> None:
    """happy: CLOSED cycle with prior visit_id → ensure today without order/relink."""
    next_day = datetime(2026, 9, 25, 10, 0, tzinfo=_TZ)
    cycle_store = _MemoryCycleStore()
    cycle = _open_cycle(cycle_store, machine_code="701")
    cycle.link_visit("scheduled:701:2026-09-24")
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycle.close(at=_AT)
    cycle_store.save(cycle)
    ensure = _RecordingEnsureOpen(visit_id="scheduled:701:2026-09-25")
    pending_store = InMemoryPendingMicromarketInventStore()
    uc = _accept_now(
        cycle_store=cycle_store,
        pending_store=pending_store,
        ensure_open_visit=ensure,
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("2")},
        inventory_id="inv-next-day",
        submitted_at=next_day,
        as_of_from_form=None,
    )
    assert len(ensure.calls) == 1
    assert ensure.calls[0]["loading_order_id"] is None
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.status is OrderStatus.CLOSED
    assert loaded.visit_id == "scheduled:701:2026-09-24"
    assert pending_store.get_for_machine("701") is not None


def test_accept_now_open_order_links_visit_once() -> None:
    """happy: OPEN cycle without visit → ensure passes order_id and links."""
    cycle_store = _MemoryCycleStore()
    _open_cycle(cycle_store, machine_code="701")
    ensure = _RecordingEnsureOpen(visit_id="scheduled:701:2026-09-24")
    pending_store = InMemoryPendingMicromarketInventStore()
    uc = _accept_now(
        cycle_store=cycle_store,
        pending_store=pending_store,
        ensure_open_visit=ensure,
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("2")},
        inventory_id="inv-link",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    assert ensure.calls[0]["loading_order_id"] == "order-701"
    loaded = cycle_store.load("701")
    assert loaded is not None
    assert loaded.visit_id == "scheduled:701:2026-09-24"
    assert pending_store.get_for_machine("701") is not None


def test_accept_now_open_order_rejects_cross_day_relink() -> None:
    """error: OPEN cycle already linked to another visit → cannot invent-relink."""
    next_day = datetime(2026, 9, 25, 10, 0, tzinfo=_TZ)
    cycle_store = _MemoryCycleStore()
    cycle = _open_cycle(cycle_store, machine_code="701")
    cycle.link_visit("scheduled:701:2026-09-24")
    cycle_store.save(cycle)
    ensure = _RecordingEnsureOpen(visit_id="scheduled:701:2026-09-25")
    uc = _accept_now(cycle_store=cycle_store, ensure_open_visit=ensure)
    with pytest.raises(ValueError, match="already linked"):
        uc.execute(
            mode="now",
            machine_code="701",
            quantities={"2311": Decimal("2")},
            inventory_id="inv-relink",
            submitted_at=next_day,
            as_of_from_form=None,
        )


def test_accept_now_second_rejected_after_pending_freeze() -> None:
    """edge: second now after pending rejected; ensure once; no complete."""
    stock_store = InMemoryMicromarketDeviceStockStore()
    ensure = _RecordingEnsureOpen()
    pending_store = InMemoryPendingMicromarketInventStore()
    complete = _RecordingCompleteOpen()
    uc = _accept_now(
        stock_store=stock_store,
        pending_store=pending_store,
        ensure_open_visit=ensure,
        complete_open_visit=complete,
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"2311": Decimal("1")},
        inventory_id="inv-1",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    with pytest.raises(VisitFinalizedRecountRejected):
        uc.execute(
            mode="now",
            machine_code="701",
            quantities={"2311": Decimal("2")},
            inventory_id="inv-2",
            submitted_at=_AT,
            as_of_from_form=None,
        )
    assert len(ensure.calls) == 1
    assert complete.calls == []


def test_completed_visit_task_finalizes_without_maintenance_completed() -> None:
    """happy: completed VisitTask → VisitFinalized true without MC."""
    from src.application.service_visits.memory import InMemoryServiceVisitStore
    from src.application.service_visits.models import (
        CloseType,
        ServiceVisit,
        VisitKind,
        VisitStatus,
    )
    from src.domain.ids import EventId, MachineId, TechnicianId
    from src.infrastructure.composition.adapters.event_store_visit_finalized_for_day import (
        EventStoreVisitFinalizedForDay,
    )
    from src.infrastructure.memory import InMemoryEventStore

    visit_store = InMemoryServiceVisitStore()
    visit_store.upsert(
        ServiceVisit(
            visit_id="field:701:2026-09-24",
            machine_id=MachineId("701"),
            kind=VisitKind.SCHEDULED,
            due_date=_AT.date(),
            status=VisitStatus.COMPLETED,
            closable=False,
            priority_boost=False,
            incident_source=None,
            close_type=CloseType.SPONTANEOUS,
            completed_at=_AT,
            completed_by_technician_id=TechnicianId("001"),
            maintenance_event_id=EventId("mnt-1"),
            created_at=_AT,
            updated_at=_AT,
        )
    )
    finalized = EventStoreVisitFinalizedForDay(
        event_store=InMemoryEventStore(),
        timezone=_TZ,
        day_end_hour=6,
        visit_store=visit_store,
    )
    assert finalized.is_finalized("701", _AT) is True
    stock_store = InMemoryMicromarketDeviceStockStore()
    _seed_shelf(stock_store, machine_code="701", qty=Decimal("1"), inventory_id="seed")
    uc = AcceptMicromarketInventory(
        stock_store=stock_store,
        sales_after=InMemoryMicromarketSalesAfter([]),
        visit_finalized=finalized,
    )
    with pytest.raises(VisitFinalizedRecountRejected):
        uc.execute(
            mode="now",
            machine_code="701",
            quantities={"2311": Decimal("9")},
            inventory_id="inv-blocked",
            submitted_at=_AT,
            as_of_from_form=None,
        )
    assert stock_store.load("701").qty("2311") == Decimal("1")


def test_maintenance_completed_fallback_finalizes_without_completed_visit() -> None:
    """edge: only MC (no completed visit) → VisitFinalized fallback true."""
    from src.domain.ids import EventId, MachineId, TechnicianId
    from src.domain.machine_operations.events import MaintenanceCompleted
    from src.infrastructure.composition.adapters.event_store_visit_finalized_for_day import (
        EventStoreVisitFinalizedForDay,
    )
    from src.infrastructure.memory import InMemoryEventStore

    event_store = InMemoryEventStore()
    event_store.append(
        MaintenanceCompleted(
            event_id=EventId("mnt-only"),
            technician_id=TechnicianId("001"),
            machine_id=MachineId("701"),
            completed_at=_AT,
            occurred_at=_AT,
        ),
        expected_version=0,
    )
    finalized = EventStoreVisitFinalizedForDay(
        event_store=event_store,
        timezone=_TZ,
        day_end_hour=6,
        visit_store=None,
    )
    assert finalized.is_finalized("701", _AT) is True


def test_recounted_complete_closes_order_and_finalizes_via_visit() -> None:
    """happy: recounted + CloseServiceVisit + close order → finalized by VisitTask."""
    from src.application.master_data import MachineKind
    from src.application.micromarket_loading.complete_maintenance_gate import (
        MicromarketCompleteMaintenanceInventoryGate,
    )
    from src.application.service_visits.close_visit import CloseServiceVisit
    from src.application.service_visits.ensure_open_visit_task import EnsureOpenVisitTask
    from src.application.service_visits.memory import InMemoryServiceVisitStore
    from src.application.service_visits.models import VisitStatus, VisitTaskSource
    from src.domain.ids import EventId, MachineId, TechnicianId
    from src.infrastructure.composition.adapters.event_store_visit_finalized_for_day import (
        EventStoreVisitFinalizedForDay,
    )
    from src.infrastructure.memory import InMemoryEventStore
    from src.infrastructure.testing.micromarket_loading_fakes import StaticMachineKindLookup

    machine = MachineId("701")
    visit_store = InMemoryServiceVisitStore()
    EnsureOpenVisitTask(store=visit_store).execute(
        machine_id=machine,
        ops_day=_AT.date(),
        source=VisitTaskSource.FIELD_ACTIVITY,
        now=_AT,
    )
    cycle_store = _MemoryCycleStore()
    _open_cycle(cycle_store, machine_code="701")
    cycle = cycle_store.load("701")
    assert cycle is not None
    cycle.mark_recounted(
        at=_AT,
        deltas=(("2311", Decimal("1")),),
        shelf_before=(("2311", Decimal("1")),),
    )
    cycle_store.save(cycle)

    CloseServiceVisit(store=visit_store).execute(
        machine_id=machine,
        technician_id=TechnicianId("001"),
        maintenance_event_id=EventId("mnt-final"),
        completed_at=_AT,
        service_weekdays=frozenset(),
        timezone=_TZ,
        day_end_hour=6,
        now=_AT,
    )
    gate = MicromarketCompleteMaintenanceInventoryGate(
        kind_lookup=StaticMachineKindLookup({"701": MachineKind.MICRO_MARKET}),
        stock_store=InMemoryMicromarketDeviceStockStore(),
        timezone=_TZ,
        day_end_hour=6,
        order_store=cycle_store,
    )
    gate.close_loading_order_after_visit_final(machine)
    closed = cycle_store.load("701")
    assert closed is not None
    assert closed.status is OrderStatus.CLOSED

    completed = visit_store.list_for_machine(machine, status=VisitStatus.COMPLETED)
    assert len(completed) == 1
    finalized = EventStoreVisitFinalizedForDay(
        event_store=InMemoryEventStore(),
        timezone=_TZ,
        day_end_hour=6,
        visit_store=visit_store,
    )
    assert finalized.is_finalized("701", _AT) is True


def test_accept_now_with_loading_order_does_not_enqueue_shop_list() -> None:
    """happy: Accept now does not auto-publish loading_shelf (deferred to squeeze)."""
    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    journal = InMemoryShopListPublishJournal()
    cycle_store = _MemoryCycleStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    _open_cycle(
        cycle_store,
        machine_code="701",
        lines=(_draft_line(product_code="n-1", launch_qty=Decimal("2")),),
    )
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_planogram_line("", domain_product_id="prod-1"),),
            updated_at=_AT,
        )
    )
    uc = _accept_now(
        stock_store=stock_store,
        cycle_store=cycle_store,
        pending_store=pending_store,
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
        complete_open_visit=_RecordingCompleteOpen(),
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"n-1": Decimal("3")},
        inventory_id="inv-loading-shelf",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    assert publisher.events == []
    assert journal.list_newest() == ()
    assert pending_store.get_for_machine("701") is not None


def test_accept_now_does_not_enqueue_even_when_shelf_would_diff() -> None:
    """edge: Accept now never enqueues shop-list; pending only."""
    from src.application.micromarket_loading.shop_list import ShopListPublishStatus

    products = _domain_products_n1_n2()
    stock_store = InMemoryMicromarketDeviceStockStore()
    planogram_store = InMemoryMicromarketPlanogramStore()
    publisher = _AcceptPublisher()
    journal = InMemoryShopListPublishJournal()
    baseline = InMemoryShopListLastSucceededSnapshotStore()
    pending_store = InMemoryPendingMicromarketInventStore()
    baseline.upsert(
        ShopListLastSucceededSnapshot(
            machine_code="701",
            lines=(ShopListIntendedLine("n-1", Decimal("10"), 6348, False),),
            updated_at=_AT,
        )
    )
    cycle_store = _MemoryCycleStore()
    _open_cycle(
        cycle_store,
        machine_code="701",
        lines=(_draft_line(product_code="n-1", launch_qty=Decimal("2")),),
    )
    planogram_store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_planogram_line("", domain_product_id="prod-1"),),
            updated_at=_AT,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=_AT,
        quantities={"n-1": Decimal("1")},
        inventory_id="seed-pub",
        partial=True,
    )
    stock_store.save(stock)
    uc = _accept_now(
        stock_store=stock_store,
        cycle_store=cycle_store,
        pending_store=pending_store,
        planogram_store=planogram_store,
        publisher=publisher,
        products=products,
        journal=journal,
        baseline_store=baseline,
        complete_open_visit=_RecordingCompleteOpen(),
    )
    uc.execute(
        mode="now",
        machine_code="701",
        quantities={"n-1": Decimal("3")},
        inventory_id="inv-no-diff",
        submitted_at=_AT,
        as_of_from_form=None,
    )
    assert publisher.events == []
    assert journal.list_newest() == ()
    assert stock_store.load("701").qty("n-1") == Decimal("1")
