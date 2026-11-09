from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
)
from src.application.micromarket_loading.publish_job import (
    AlreadyPublishing,
    CommandRejected,
    Enqueued,
    MicromarketShopListPublishHandler,
    MissingGroup,
    NothingToSend,
    PreflightFailed,
    SnapshotStale,
    Synced,
    TemplateWriteFailed,
    enqueue_micromarket_shop_list_publish,
    mark_shop_list_publication_failed,
)
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.micromarket_loading.shop_list_publish_journal import (
    ShopListIntendedLine,
    ShopListLastSucceededSnapshot,
    ShopListPublishEffects,
    ShopListPublishJournalEntry,
    ShopListPublishJournalStatus,
    ShopListPublishTrigger,
)
from src.application.product_identity import DomainProduct
from src.domain.ids import EventId
from src.domain.micromarket_loading import MicromarketDeviceStock
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested
from src.infrastructure.integrations.kitshop.http_client import (
    KitShopNetworkError,
    KitShopResponseError,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketDeviceStockStore,
    InMemoryMicromarketPlanogramStore,
    InMemoryShopListLastSucceededSnapshotStore,
    InMemoryShopListPublishJournal,
)

_ACTIVE_ID = "prod-active"
_ACTIVE_NUMBER = f"n-{_ACTIVE_ID}"
_P1 = "prod-1"
_P2 = "prod-2"
_N1 = f"n-{_P1}"
_N2 = f"n-{_P2}"


class _Publisher:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def _product(
    domain_product_id: str,
    name: str,
    catalog_code: str | None,
) -> DomainProduct:
    return DomainProduct(
        domain_product_id=domain_product_id,
        number=f"n-{domain_product_id}",
        name=name,
        catalog_code=catalog_code,
        hidden=False,
    )


def _linked(
    domain_product_id: str,
    *,
    price: Decimal = Decimal("15"),
    kit_group_id: int | None = 6348,
    sort_order: int = 0,
) -> MicromarketPlanogramLine:
    return MicromarketPlanogramLine(
        product_code="",
        target_qty=1,
        price_rub=price,
        active=True,
        sort_order=sort_order,
        kit_group_id=kit_group_id,
        domain_product_id=domain_product_id,
    )


def _planogram_with(
    *lines: MicromarketPlanogramLine,
    status: ShopListPublishStatus = ShopListPublishStatus.UNPUBLISHED,
) -> MicromarketPlanogram:
    ordered = tuple(
        MicromarketPlanogramLine(
            product_code=line.product_code,
            target_qty=line.target_qty,
            price_rub=line.price_rub,
            active=line.active,
            sort_order=index,
            kit_group_id=line.kit_group_id,
            domain_product_id=line.domain_product_id,
        )
        for index, line in enumerate(lines)
    )
    return MicromarketPlanogram(
        machine_code="701",
        lines=ordered,
        updated_at=datetime(2026, 9, 28, tzinfo=UTC),
        shop_list_status=status,
    )


def _save_active(
    store: InMemoryMicromarketPlanogramStore,
    *,
    price: Decimal,
    group: int,
) -> FakeDomainProductStore:
    products = FakeDomainProductStore()
    products.insert(_product(_ACTIVE_ID, "Салат", None))
    store.upsert(
        _planogram_with(_linked(_ACTIVE_ID, price=price, kit_group_id=group)),
    )
    return products


def _publishing_setup() -> tuple[
    InMemoryMicromarketPlanogramStore,
    FakeDomainProductStore,
    MicromarketShopListPublishRequested,
]:
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("10"), group=6348)
    publisher = _Publisher()
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
    )
    assert isinstance(result, Enqueued)
    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)
    return store, products, event


class _Gateway:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls = 0
        self.command_calls = 0
        self.rollback_calls = 0
        self.catalog_names: object = ()

    def sync_snapshot(
        self,
        *,
        machine_code: str,
        lines: object,
        snapshot_still_current: object = None,
        catalog_names: object = (),
    ) -> object:
        del machine_code, lines, snapshot_still_current
        self.catalog_names = catalog_names
        self.calls += 1
        return self._result


def test_enqueue_empty_publishable_snapshot_keeps_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        _planogram_with(
            MicromarketPlanogramLine("2311", 1, Decimal("15"), True, 0, 6348),
            status=ShopListPublishStatus.PUBLISHED,
        )
    )
    publisher = _Publisher()
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 28, tzinfo=UTC),
    )
    assert isinstance(result, NothingToSend)
    assert result.skipped_names == ("2311",)
    assert publisher.events == []
    assert store.get("701").shop_list_status is ShopListPublishStatus.PUBLISHED


def test_enqueue_partial_snapshot_publishes_linked_lines() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(_P2, "Сок", "2400"))
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        _planogram_with(
            MicromarketPlanogramLine("legacy", 1, Decimal("15"), True, 0, None),
            _linked(_P2, price=Decimal("20")),
        )
    )
    publisher = _Publisher()
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 28, tzinfo=UTC),
        products=products,
    )
    assert isinstance(result, Enqueued)
    assert result.skipped_names == ("legacy",)
    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)
    assert event.lines[0][0] == _N2
    assert store.get("701").shop_list_status is ShopListPublishStatus.PUBLISHING


def test_enqueue_sets_publishing_and_one_event() -> None:
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("10"), group=6348)
    published: list[MicromarketShopListPublishRequested] = []

    class _LocalPublisher:
        def publish(self, event: MicromarketShopListPublishRequested) -> None:
            published.append(event)

    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_LocalPublisher(),
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
    )
    assert isinstance(result, Enqueued)
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.PUBLISHING
    assert doc.shop_list_publication_id == result.publication_id
    assert len(published) == 1
    assert published[0].event_id.value == result.publication_id
    assert published[0].lines == ((_ACTIVE_NUMBER, "10", 6348, False),)


def test_enqueue_while_publishing_sets_catch_up_without_second_event() -> None:
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("10"), group=6348)
    published: list[object] = []

    class _LocalPublisher:
        def publish(self, event: object) -> None:
            published.append(event)

    enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_LocalPublisher(),
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
    )
    second = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_LocalPublisher(),
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
    )
    assert isinstance(second, AlreadyPublishing)
    assert len(published) == 1
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_catch_up_requested is True


def test_enqueue_includes_last_factual_zero_as_disabled_in_event_lines() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(_P1, "A", None))
    products.insert(_product(_P2, "B", None))
    store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    store.upsert(
        _planogram_with(
            _linked(_P1, price=Decimal("10")),
            _linked(_P2, price=Decimal("20")),
        )
    )
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 25, tzinfo=UTC),
        quantities={_N1: Decimal("0"), _N2: Decimal("2")},
        inventory_id="enq-filter",
        partial=True,
    )
    stock_store.save(stock)
    publisher = _Publisher()
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
        stock_store=stock_store,
    )
    assert isinstance(result, Enqueued)
    assert len(publisher.events) == 1
    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)
    assert event.lines == ((_N1, "10", 6348, True), (_N2, "20", 6348, False))


def test_enqueue_publishes_disabled_lines_when_all_active_have_factual_zero() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(_P1, "A", None))
    store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    store.upsert(_planogram_with(_linked(_P1, price=Decimal("10"))))
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 25, tzinfo=UTC),
        quantities={_N1: Decimal("0")},
        inventory_id="all-zero",
        partial=True,
    )
    stock_store.save(stock)
    publisher = _Publisher()
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
        stock_store=stock_store,
    )
    assert isinstance(result, Enqueued)
    assert publisher.events[0].lines == ((_N1, "10", 6348, True),)


def test_enqueue_publishes_empty_lines_when_planogram_has_no_lines() -> None:
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(),
            updated_at=datetime(2026, 9, 25, tzinfo=UTC),
        )
    )
    publisher = _Publisher()
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
    )
    assert isinstance(result, Enqueued)
    assert publisher.events[0].lines == ()


def test_enqueue_rejects_active_line_without_group() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(_P1, "A", None))
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(_planogram_with(_linked(_P1, kit_group_id=None)))
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
    )
    assert isinstance(result, MissingGroup)
    assert result.product_code == _N1
    assert store.get("701").shop_list_status is ShopListPublishStatus.UNPUBLISHED


def test_enqueue_after_failed_emits_new_event() -> None:
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("10"), group=6348)
    current = store.get("701")
    assert current is not None
    store.upsert(
        MicromarketPlanogram(
            machine_code=current.machine_code,
            lines=current.lines,
            updated_at=current.updated_at,
            shop_list_status=ShopListPublishStatus.FAILED,
            shop_list_error="База товаров на терминал не ушла",
            shop_list_publication_id="old",
        ),
    )
    publisher = _Publisher()
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
    )
    assert isinstance(result, Enqueued)
    assert len(publisher.events) == 1
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHING
    assert updated.shop_list_publication_id != "old"


class _RaisingPublisher:
    def publish(self, event: object) -> None:
        raise RuntimeError("publish down")


def test_enqueue_publish_failure_restores_status() -> None:
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("10"), group=6348)
    before = store.get("701")
    assert before is not None
    with pytest.raises(RuntimeError, match="publish down"):
        enqueue_micromarket_shop_list_publish(
            store=store,
            publisher=_RaisingPublisher(),
            machine_code="701",
            now=datetime(2026, 9, 25, tzinfo=UTC),
            products=products,
        )
    after = store.get("701")
    assert after is not None
    assert after.shop_list_status is not ShopListPublishStatus.PUBLISHING
    assert after.shop_list_status == before.shop_list_status
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
    )
    assert isinstance(result, Enqueued)
    assert len(result.publication_id) > 0


def test_handler_sets_published_only_after_command_accepted() -> None:
    store, _products, event = _publishing_setup()
    handler = MicromarketShopListPublishHandler(store=store, gateway=_Gateway(Synced()))
    handler.process(event)
    assert store.get("701").shop_list_status is ShopListPublishStatus.PUBLISHED
    assert store.get("701").shop_list_error == ""


def test_handler_command_rejection_keeps_template_and_sets_failed() -> None:
    store, _products, event = _publishing_setup()
    gateway = _Gateway(CommandRejected("База товаров на терминал не ушла"))
    MicromarketShopListPublishHandler(store=store, gateway=gateway).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert updated.shop_list_error == "База товаров на терминал не ушла"
    assert gateway.rollback_calls == 0


def test_handler_planogram_change_skips_command() -> None:
    store, _products, event = _publishing_setup()
    gateway = _Gateway(SnapshotStale())
    MicromarketShopListPublishHandler(store=store, gateway=gateway).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert updated.shop_list_error == "Планограмма изменилась во время публикации"
    assert gateway.command_calls == 0


def test_handler_replay_after_published_does_not_call_kit() -> None:
    store, _products, event = _publishing_setup()
    doc = store.get("701")
    assert doc is not None
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=doc.lines,
            updated_at=doc.updated_at,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id=doc.shop_list_publication_id,
        ),
    )
    gateway = _Gateway(Synced())
    MicromarketShopListPublishHandler(store=store, gateway=gateway).process(event)
    assert gateway.calls == 0


def test_handler_ignores_event_when_publication_id_differs() -> None:
    store, _products, event = _publishing_setup()
    doc = store.get("701")
    assert doc is not None
    status_before = doc.shop_list_status
    gateway = _Gateway(Synced())
    other = MicromarketShopListPublishRequested(
        event_id=EventId("other-id"),
        machine_code=doc.machine_code,
        publication_id="other-id",
        lines=event.lines,
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
    )
    MicromarketShopListPublishHandler(store=store, gateway=gateway).process(other)
    assert gateway.calls == 0
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is status_before
    assert updated.shop_list_publication_id == doc.shop_list_publication_id


def test_handler_preflight_failure_sets_failed() -> None:
    store, _products, event = _publishing_setup()
    MicromarketShopListPublishHandler(
        store=store,
        gateway=_Gateway(PreflightFailed("Нужна одна витрина")),
    ).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert updated.shop_list_error == "Нужна одна витрина"


def test_handler_template_write_failure_sets_kit_message() -> None:
    store, _products, event = _publishing_setup()
    MicromarketShopListPublishHandler(
        store=store,
        gateway=_Gateway(TemplateWriteFailed("kit write")),
    ).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert updated.shop_list_error == "kit write"


def test_handler_network_error_is_reraised() -> None:
    store, _products, event = _publishing_setup()

    class _NetworkGateway:
        calls = 0

        def sync_snapshot(
            self,
            *,
            machine_code: str,
            lines: object,
            snapshot_still_current: object = None,
            catalog_names: object = (),
        ) -> object:
            del machine_code, lines, snapshot_still_current, catalog_names
            self.calls += 1
            raise KitShopNetworkError("timeout")

    gateway = _NetworkGateway()
    with pytest.raises(KitShopNetworkError):
        MicromarketShopListPublishHandler(store=store, gateway=gateway).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHING


def test_handler_resumes_failed_matching_publication() -> None:
    store, products, event = _publishing_setup()
    mark_shop_list_publication_failed(store, event.publication_id, "timeout")
    gateway = _Gateway(Synced())
    MicromarketShopListPublishHandler(
        store=store,
        gateway=gateway,
        products=products,
    ).process(event)
    assert gateway.calls == 1
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHED
    assert updated.shop_list_error == ""


def test_handler_resume_sets_journal_running_then_succeeded() -> None:
    store, products, event = _publishing_setup()
    journal = InMemoryShopListPublishJournal()
    now = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
    journal.append(
        ShopListPublishJournalEntry(
            publication_id=event.publication_id,
            machine_code="701",
            status=ShopListPublishJournalStatus.FAILED,
            created_at=now,
            updated_at=now,
            error_message="timeout",
        )
    )
    mark_shop_list_publication_failed(store, event.publication_id, "timeout")
    seen: list[ShopListPublishJournalStatus] = []

    class _ResumeGateway:
        def sync_snapshot(
            self,
            *,
            machine_code: str,
            lines: object,
            snapshot_still_current: object = None,
            catalog_names: object = (),
        ) -> object:
            del machine_code, lines, snapshot_still_current, catalog_names
            rows = journal.list_newest()
            assert rows
            seen.append(rows[0].status)
            return Synced()

    MicromarketShopListPublishHandler(
        store=store,
        gateway=_ResumeGateway(),
        products=products,
        journal=journal,
        now_factory=lambda: datetime(2026, 10, 26, 12, 5, tzinfo=UTC),
    ).process(event)
    assert seen == [ShopListPublishJournalStatus.RUNNING]
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].status is ShopListPublishJournalStatus.SUCCEEDED
    assert rows[0].error_message == ""


def test_handler_ignores_failed_when_publication_id_mismatch() -> None:
    store, _products, event = _publishing_setup()
    mark_shop_list_publication_failed(store, event.publication_id, "timeout")
    gateway = _Gateway(Synced())
    other = MicromarketShopListPublishRequested(
        event_id=EventId("other-id"),
        machine_code="701",
        publication_id="other-id",
        lines=event.lines,
        occurred_at=datetime(2026, 10, 26, tzinfo=UTC),
    )
    MicromarketShopListPublishHandler(store=store, gateway=gateway).process(other)
    assert gateway.calls == 0
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED


def test_handler_network_after_resume_leaves_publishing() -> None:
    store, _products, event = _publishing_setup()
    mark_shop_list_publication_failed(store, event.publication_id, "timeout")

    class _NetworkGateway:
        def sync_snapshot(
            self,
            *,
            machine_code: str,
            lines: object,
            snapshot_still_current: object = None,
            catalog_names: object = (),
        ) -> object:
            del machine_code, lines, snapshot_still_current, catalog_names
            raise KitShopNetworkError("again")

    with pytest.raises(KitShopNetworkError):
        MicromarketShopListPublishHandler(store=store, gateway=_NetworkGateway()).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHING
    assert updated.shop_list_error == ""


def test_terminal_failure_marks_publishing_as_failed() -> None:
    store, _products, event = _publishing_setup()
    mark_shop_list_publication_failed(store, event.publication_id, "timeout")
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert updated.shop_list_error == "timeout"


def test_terminal_failure_does_not_clobber_published() -> None:
    store, _products, event = _publishing_setup()
    doc = store.get("701")
    assert doc is not None
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=doc.lines,
            updated_at=doc.updated_at,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id=doc.shop_list_publication_id,
        ),
    )
    mark_shop_list_publication_failed(store, event.publication_id, "timeout")
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHED


def test_handler_keeps_publishable_snapshot_current_for_domain_numbers() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(_P1, "Кефир", None))
    products.insert(_product(_P2, "Сок", "2400"))
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(
        _planogram_with(
            _linked(_P1),
            _linked(_P2, price=Decimal("20")),
        )
    )
    publisher = _Publisher()
    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 28, tzinfo=UTC),
        products=products,
    )
    assert isinstance(result, Enqueued)
    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)
    assert event.lines[0][0] == _N1
    assert event.lines[1][0] == _N2

    class _CallbackGateway:
        def sync_snapshot(
            self,
            *,
            machine_code: str,
            lines: object,
            snapshot_still_current: object = None,
            catalog_names: object = (),
        ) -> object:
            del machine_code, lines, catalog_names
            assert callable(snapshot_still_current)
            if not snapshot_still_current():
                return SnapshotStale()
            return Synced()

    MicromarketShopListPublishHandler(
        store=store,
        gateway=_CallbackGateway(),
        products=products,
    ).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHED


def test_handler_marks_stale_when_linked_line_price_changes() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(_P2, "Сок", "2400"))
    store = InMemoryMicromarketPlanogramStore()
    store.upsert(_planogram_with(_linked(_P2, price=Decimal("20"))))
    publisher = _Publisher()
    enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 28, tzinfo=UTC),
        products=products,
    )
    event = publisher.events[0]
    doc = store.get("701")
    assert doc is not None
    changed = _planogram_with(_linked(_P2, price=Decimal("25")))
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=changed.lines,
            updated_at=doc.updated_at,
            shop_list_status=doc.shop_list_status,
            shop_list_error=doc.shop_list_error,
            shop_list_publication_id=doc.shop_list_publication_id,
        )
    )

    class _CallbackGateway:
        def sync_snapshot(
            self,
            *,
            machine_code: str,
            lines: object,
            snapshot_still_current: object = None,
            catalog_names: object = (),
        ) -> object:
            del machine_code, lines, catalog_names
            assert callable(snapshot_still_current)
            if not snapshot_still_current():
                return SnapshotStale()
            return Synced()

    MicromarketShopListPublishHandler(
        store=store,
        gateway=_CallbackGateway(),
        products=products,
    ).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert updated.shop_list_error == "Планограмма изменилась во время публикации"


def test_handler_catch_up_enqueues_filtered_follow_up_after_synced() -> None:
    products = FakeDomainProductStore()
    products.insert(_product(_P1, "A", None))
    products.insert(_product(_P2, "B", None))
    store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    store.upsert(
        _planogram_with(
            _linked(_P1, price=Decimal("10")),
            _linked(_P2, price=Decimal("20")),
        )
    )
    publisher = _Publisher()
    first = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
        stock_store=stock_store,
    )
    assert isinstance(first, Enqueued)
    assert first.publication_id
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 25, 1, tzinfo=UTC),
        quantities={_N1: Decimal("0"), _N2: Decimal("2")},
        inventory_id="catch-up-inv",
        partial=True,
    )
    stock_store.save(stock)
    second = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, 1, tzinfo=UTC),
        products=products,
        stock_store=stock_store,
    )
    assert isinstance(second, AlreadyPublishing)
    assert len(publisher.events) == 1
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_catch_up_requested is True
    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)

    class _FinishGateway:
        def __init__(self) -> None:
            self.saw_still_current = False

        def sync_snapshot(
            self,
            *,
            machine_code: str,
            lines: object,
            snapshot_still_current: object = None,
            catalog_names: object = (),
        ) -> object:
            del machine_code, lines, catalog_names
            assert callable(snapshot_still_current)
            self.saw_still_current = bool(snapshot_still_current())
            return Synced()

    gateway = _FinishGateway()
    handler = MicromarketShopListPublishHandler(
        store=store,
        gateway=gateway,
        products=products,
        stock_store=stock_store,
        event_publisher=publisher,
        now_factory=lambda: datetime(2026, 9, 25, 2, tzinfo=UTC),
    )
    handler.process(event)
    assert gateway.saw_still_current is True
    assert len(publisher.events) == 2
    follow = publisher.events[1]
    assert isinstance(follow, MicromarketShopListPublishRequested)
    assert follow.lines == ((_N1, "10", 6348, True), (_N2, "20", 6348, False))
    latest = store.get("701")
    assert latest is not None
    assert latest.shop_list_status is ShopListPublishStatus.PUBLISHING
    assert latest.shop_list_catch_up_requested is False
    assert latest.shop_list_publication_id == follow.publication_id


def test_handler_catch_up_still_current_when_planogram_changed() -> None:
    """Текущее задание доводит frozen event.lines; смена планограммы не даёт SnapshotStale."""
    store, products, event = _publishing_setup()
    doc = store.get("701")
    assert doc is not None
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=doc.lines,
            updated_at=doc.updated_at,
            shop_list_status=doc.shop_list_status,
            shop_list_error=doc.shop_list_error,
            shop_list_publication_id=doc.shop_list_publication_id,
            shop_list_catch_up_requested=True,
        ),
    )
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=(),
            updated_at=doc.updated_at,
            shop_list_status=ShopListPublishStatus.PUBLISHING,
            shop_list_publication_id=doc.shop_list_publication_id,
            shop_list_catch_up_requested=True,
        ),
    )

    class _CheckGateway:
        def sync_snapshot(
            self,
            *,
            machine_code,
            lines,
            snapshot_still_current=None,
            catalog_names=(),
        ):
            del machine_code, lines, catalog_names
            assert callable(snapshot_still_current)
            assert snapshot_still_current() is True
            return Synced()

    publisher = _Publisher()
    MicromarketShopListPublishHandler(
        store=store,
        gateway=_CheckGateway(),
        products=products,
        event_publisher=publisher,
        now_factory=lambda: datetime(2026, 9, 25, tzinfo=UTC),
        stock_store=InMemoryMicromarketDeviceStockStore(),
    ).process(event)
    assert len(publisher.events) == 1
    assert publisher.events[0].lines == ()


def test_handler_catch_up_enqueues_follow_up_after_command_rejected() -> None:
    """Отказ Kit не откатывает факт; после FAILED — один выпуск с новым фильтром."""
    products = FakeDomainProductStore()
    products.insert(_product(_P1, "A", None))
    products.insert(_product(_P2, "B", None))
    store = InMemoryMicromarketPlanogramStore()
    stock_store = InMemoryMicromarketDeviceStockStore()
    store.upsert(
        _planogram_with(
            _linked(_P1, price=Decimal("10")),
            _linked(_P2, price=Decimal("20")),
        )
    )
    publisher = _Publisher()
    first = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
        stock_store=stock_store,
    )
    assert isinstance(first, Enqueued)
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 9, 25, 1, tzinfo=UTC),
        quantities={_N1: Decimal("0"), _N2: Decimal("2")},
        inventory_id="catch-up-fail",
        partial=True,
    )
    stock_store.save(stock)
    second = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=datetime(2026, 9, 25, 1, tzinfo=UTC),
        products=products,
        stock_store=stock_store,
    )
    assert isinstance(second, AlreadyPublishing)
    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)

    class _RejectGateway:
        def sync_snapshot(
            self,
            *,
            machine_code: str,
            lines: object,
            snapshot_still_current: object = None,
            catalog_names: object = (),
        ) -> object:
            del machine_code, lines, snapshot_still_current, catalog_names
            return CommandRejected("База товаров на терминал не ушла")

    MicromarketShopListPublishHandler(
        store=store,
        gateway=_RejectGateway(),
        products=products,
        stock_store=stock_store,
        event_publisher=publisher,
        now_factory=lambda: datetime(2026, 9, 25, 2, tzinfo=UTC),
    ).process(event)
    assert len(publisher.events) == 2
    follow = publisher.events[1]
    assert isinstance(follow, MicromarketShopListPublishRequested)
    assert follow.lines == ((_N1, "10", 6348, True), (_N2, "20", 6348, False))
    latest = store.get("701")
    assert latest is not None
    assert latest.shop_list_status is ShopListPublishStatus.PUBLISHING
    assert latest.shop_list_catch_up_requested is False
    assert latest.shop_list_publication_id == follow.publication_id


def test_handler_passes_catalog_names_without_changing_event_lines() -> None:
    store, products, event = _publishing_setup()
    assert event.lines == ((_ACTIVE_NUMBER, "10", 6348, False),)
    gateway = _Gateway(Synced())
    MicromarketShopListPublishHandler(
        store=store,
        gateway=gateway,
        products=products,
    ).process(event)
    assert gateway.catalog_names == ((_ACTIVE_NUMBER, "Салат"),)
    assert event.lines == ((_ACTIVE_NUMBER, "10", 6348, False),)
    assert all(len(row) == 4 for row in event.lines)
    assert store.get("701").shop_list_status is ShopListPublishStatus.PUBLISHED


def test_handler_catalog_ensure_failure_sets_failed_with_product_code() -> None:
    store, products, event = _publishing_setup()
    MicromarketShopListPublishHandler(
        store=store,
        gateway=_Gateway(PreflightFailed("Несколько живых карточек Kit для товара n-prod-active")),
        products=products,
    ).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert "n-prod-active" in updated.shop_list_error


def test_handler_catalog_ensure_kit_response_error_keeps_publishing() -> None:
    store, products, event = _publishing_setup()

    class _RaiseGateway:
        def sync_snapshot(
            self,
            *,
            machine_code: str,
            lines: object,
            snapshot_still_current: object = None,
            catalog_names: object = (),
        ) -> object:
            del machine_code, lines, snapshot_still_current, catalog_names
            raise KitShopResponseError("kit add failed", 9)

    with pytest.raises(KitShopResponseError, match="kit add failed"):
        MicromarketShopListPublishHandler(
            store=store,
            gateway=_RaiseGateway(),
            products=products,
        ).process(event)
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHING


def test_enqueue_appends_journal_running_with_same_publication_id() -> None:
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("10"), group=6348)
    journal = InMemoryShopListPublishJournal()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=now,
        products=products,
        journal=journal,
    )

    assert isinstance(result, Enqueued)
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].publication_id == result.publication_id
    assert rows[0].machine_code == "701"
    assert rows[0].status is ShopListPublishJournalStatus.RUNNING
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.PUBLISHING
    assert doc.shop_list_publication_id == result.publication_id


def test_already_publishing_leaves_journal_unchanged() -> None:
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("10"), group=6348)
    journal = InMemoryShopListPublishJournal()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=now,
        products=products,
        journal=journal,
    )
    before = journal.list_newest()

    second = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=now,
        products=products,
        journal=journal,
    )

    assert isinstance(second, AlreadyPublishing)
    assert journal.list_newest() == before
    doc = store.get("701")
    assert doc is not None
    assert doc.shop_list_status is ShopListPublishStatus.PUBLISHING


def test_enqueue_supersedes_prior_running_journal_for_machine() -> None:
    # happy: second enqueue → prior RUNNING becomes FAILED (superseded)
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("10"), group=6348)
    journal = InMemoryShopListPublishJournal()
    t0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    first = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=t0,
        products=products,
        journal=journal,
    )
    assert isinstance(first, Enqueued)
    # Simulate planogram freed while orphan journal stays RUNNING (republish path).
    stuck = store.get("701")
    assert stuck is not None
    store.upsert(
        MicromarketPlanogram(
            machine_code=stuck.machine_code,
            lines=stuck.lines,
            updated_at=stuck.updated_at,
            shop_list_status=ShopListPublishStatus.FAILED,
            shop_list_error="stale",
            shop_list_publication_id=stuck.shop_list_publication_id,
            shelves=stuck.shelves,
        )
    )
    t1 = datetime(2026, 10, 8, 12, 5, tzinfo=UTC)
    second = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=t1,
        products=products,
        journal=journal,
    )
    assert isinstance(second, Enqueued)
    by_id = {row.publication_id: row for row in journal.list_newest()}
    prior = by_id[first.publication_id]
    assert prior.status is ShopListPublishJournalStatus.FAILED
    assert "публикац" in prior.error_message.lower() or "замен" in prior.error_message.lower()
    assert by_id[second.publication_id].status is ShopListPublishJournalStatus.RUNNING
    running = [
        row
        for row in journal.list_newest()
        if row.machine_code == "701" and row.status is ShopListPublishJournalStatus.RUNNING
    ]
    assert len(running) == 1


def test_enqueue_does_not_supersede_other_machine_running() -> None:
    # edge: other machine's RUNNING stays; this machine gets a fresh RUNNING
    store = InMemoryMicromarketPlanogramStore()
    products = FakeDomainProductStore()
    products.insert(_product(_ACTIVE_ID, "Салат", None))
    journal = InMemoryShopListPublishJournal()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    store.upsert(
        MicromarketPlanogram(
            machine_code="701",
            lines=(_linked(_ACTIVE_ID, price=Decimal("10"), kit_group_id=6348),),
            updated_at=now,
            shop_list_status=ShopListPublishStatus.UNPUBLISHED,
        )
    )
    store.upsert(
        MicromarketPlanogram(
            machine_code="702",
            lines=(_linked(_ACTIVE_ID, price=Decimal("10"), kit_group_id=6348),),
            updated_at=now,
            shop_list_status=ShopListPublishStatus.UNPUBLISHED,
        )
    )
    other = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="702",
        now=now,
        products=products,
        journal=journal,
    )
    assert isinstance(other, Enqueued)
    mine = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=now,
        products=products,
        journal=journal,
    )
    assert isinstance(mine, Enqueued)
    by_id = {row.publication_id: row for row in journal.list_newest()}
    assert by_id[other.publication_id].status is ShopListPublishJournalStatus.RUNNING
    assert by_id[mine.publication_id].status is ShopListPublishJournalStatus.RUNNING


def test_handler_synced_marks_journal_succeeded() -> None:
    store, products, event = _publishing_setup()
    journal = InMemoryShopListPublishJournal()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    journal.append(
        ShopListPublishJournalEntry(
            publication_id=event.publication_id,
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
    )

    MicromarketShopListPublishHandler(
        store=store,
        gateway=_Gateway(Synced()),
        products=products,
        journal=journal,
        now_factory=lambda: datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
    ).process(event)

    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].status is ShopListPublishJournalStatus.SUCCEEDED
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHED


def test_handler_command_rejected_marks_journal_failed() -> None:
    store, products, event = _publishing_setup()
    journal = InMemoryShopListPublishJournal()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    journal.append(
        ShopListPublishJournalEntry(
            publication_id=event.publication_id,
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
    )

    MicromarketShopListPublishHandler(
        store=store,
        gateway=_Gateway(CommandRejected("База товаров на терминал не ушла")),
        products=products,
        journal=journal,
        now_factory=lambda: datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
    ).process(event)

    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].status is ShopListPublishJournalStatus.FAILED
    assert rows[0].error_message == "База товаров на терминал не ушла"
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED


def test_enqueue_inventory_zero_writes_trigger_and_disabled_effects() -> None:
    # happy: inventory_zero enqueue → journal inventory_zero + disabled codes + running
    store = InMemoryMicromarketPlanogramStore()
    products = FakeDomainProductStore()
    products.insert(_product(_P1, "One", "c1"))
    products.insert(_product(_P2, "Two", "c2"))
    store.upsert(
        _planogram_with(
            _linked(_P1, price=Decimal("10")),
            _linked(_P2, price=Decimal("10"), sort_order=1),
        )
    )
    stock_store = InMemoryMicromarketDeviceStockStore()
    stock = MicromarketDeviceStock(machine_code="701")
    stock.apply_inventory(
        as_of=datetime(2026, 10, 8, tzinfo=UTC),
        quantities={_N1: Decimal("0"), _N2: Decimal("2")},
        inventory_id="seed",
        partial=True,
    )
    stock_store.save(stock)
    journal = InMemoryShopListPublishJournal()
    baseline = InMemoryShopListLastSucceededSnapshotStore()
    baseline.upsert(
        ShopListLastSucceededSnapshot(
            machine_code="701",
            lines=(
                ShopListIntendedLine(_N1, Decimal("10"), 6348, False),
                ShopListIntendedLine(_N2, Decimal("10"), 6348, False),
            ),
            updated_at=datetime(2026, 10, 7, tzinfo=UTC),
        )
    )
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=now,
        products=products,
        stock_store=stock_store,
        journal=journal,
        trigger=ShopListPublishTrigger.INVENTORY_ZERO,
        baseline_store=baseline,
    )

    assert isinstance(result, Enqueued)
    row = journal.list_newest()[0]
    assert row.trigger is ShopListPublishTrigger.INVENTORY_ZERO
    assert row.status is ShopListPublishJournalStatus.RUNNING
    assert _N1 in row.effects.disabled_product_codes
    assert _N1 in row.effects.updated_product_codes


def test_enqueue_manual_price_change_marks_updated() -> None:
    store = InMemoryMicromarketPlanogramStore()
    products = _save_active(store, price=Decimal("12"), group=6348)
    journal = InMemoryShopListPublishJournal()
    baseline = InMemoryShopListLastSucceededSnapshotStore()
    baseline.upsert(
        ShopListLastSucceededSnapshot(
            machine_code="701",
            lines=(ShopListIntendedLine(_ACTIVE_NUMBER, Decimal("10"), 6348, False),),
            updated_at=datetime(2026, 10, 7, tzinfo=UTC),
        )
    )

    result = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
        products=products,
        journal=journal,
        trigger=ShopListPublishTrigger.MANUAL,
        baseline_store=baseline,
    )

    assert isinstance(result, Enqueued)
    row = journal.list_newest()[0]
    assert row.trigger is ShopListPublishTrigger.MANUAL
    assert row.effects.updated_product_codes == (_ACTIVE_NUMBER,)
    assert row.baseline_lines == (ShopListIntendedLine(_ACTIVE_NUMBER, Decimal("10"), 6348, False),)
    assert any(line.price_rub == Decimal("12") for line in row.intended_lines)


def test_handler_success_updates_baseline_fail_keeps_baseline_and_effects() -> None:
    store, products, event = _publishing_setup()
    journal = InMemoryShopListPublishJournal()
    baseline = InMemoryShopListLastSucceededSnapshotStore()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    intended = (ShopListIntendedLine(_ACTIVE_NUMBER, Decimal("10"), 6348, False),)
    journal.append(
        ShopListPublishJournalEntry(
            publication_id=event.publication_id,
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=now,
            updated_at=now,
            trigger=ShopListPublishTrigger.MANUAL,
            effects=ShopListPublishEffects(added_product_codes=(_ACTIVE_NUMBER,)),
            intended_lines=intended,
        )
    )

    MicromarketShopListPublishHandler(
        store=store,
        gateway=_Gateway(Synced()),
        products=products,
        journal=journal,
        baseline_store=baseline,
        now_factory=lambda: datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
    ).process(event)

    snap = baseline.get("701")
    assert snap is not None
    assert snap.lines == intended
    assert journal.list_newest()[0].status is ShopListPublishJournalStatus.SUCCEEDED

    store2, products2, event2 = _publishing_setup()
    journal2 = InMemoryShopListPublishJournal()
    baseline2 = InMemoryShopListLastSucceededSnapshotStore()
    old = ShopListLastSucceededSnapshot(
        machine_code="701",
        lines=(ShopListIntendedLine("old", Decimal("1"), 1, False),),
        updated_at=now,
    )
    baseline2.upsert(old)
    effects = ShopListPublishEffects(disabled_product_codes=("x",))
    journal2.append(
        ShopListPublishJournalEntry(
            publication_id=event2.publication_id,
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=now,
            updated_at=now,
            trigger=ShopListPublishTrigger.INVENTORY_ZERO,
            effects=effects,
            intended_lines=intended,
        )
    )
    MicromarketShopListPublishHandler(
        store=store2,
        gateway=_Gateway(CommandRejected("boom")),
        products=products2,
        journal=journal2,
        baseline_store=baseline2,
        now_factory=lambda: datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
    ).process(event2)
    row = journal2.list_newest()[0]
    assert row.status is ShopListPublishJournalStatus.FAILED
    assert row.effects == effects
    assert baseline2.get("701") == old


def test_handler_success_missing_journal_entry_keeps_baseline() -> None:
    # edge: SUCCEEDED but journal entry missing → do not upsert empty intended_lines
    store, products, event = _publishing_setup()
    journal = InMemoryShopListPublishJournal()
    baseline = InMemoryShopListLastSucceededSnapshotStore()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    old = ShopListLastSucceededSnapshot(
        machine_code="701",
        lines=(ShopListIntendedLine("keep", Decimal("5"), 1, False),),
        updated_at=now,
    )
    baseline.upsert(old)

    MicromarketShopListPublishHandler(
        store=store,
        gateway=_Gateway(Synced()),
        products=products,
        journal=journal,
        baseline_store=baseline,
        now_factory=lambda: datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
    ).process(event)

    assert baseline.get("701") == old
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHED


def test_handler_catch_up_preserves_original_trigger() -> None:
    store = InMemoryMicromarketPlanogramStore()
    products = FakeDomainProductStore()
    products.insert(_product(_P1, "One", "c1"))
    products.insert(_product(_P2, "Two", "c2"))
    store.upsert(
        _planogram_with(
            _linked(_P1, price=Decimal("10")),
            _linked(_P2, price=Decimal("10"), sort_order=1),
        )
    )
    publisher = _Publisher()
    journal = InMemoryShopListPublishJournal()
    baseline = InMemoryShopListLastSucceededSnapshotStore()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    first = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=now,
        products=products,
        journal=journal,
        trigger=ShopListPublishTrigger.INVENTORY_ZERO,
        baseline_store=baseline,
    )
    assert isinstance(first, Enqueued)
    second = enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=publisher,
        machine_code="701",
        now=now,
        products=products,
        journal=journal,
        trigger=ShopListPublishTrigger.MANUAL,
        baseline_store=baseline,
    )
    assert isinstance(second, AlreadyPublishing)
    assert len(journal.list_newest()) == 1

    event = publisher.events[0]
    assert isinstance(event, MicromarketShopListPublishRequested)
    MicromarketShopListPublishHandler(
        store=store,
        gateway=_Gateway(Synced()),
        products=products,
        event_publisher=publisher,
        journal=journal,
        baseline_store=baseline,
        now_factory=lambda: datetime(2026, 10, 8, 12, 5, tzinfo=UTC),
    ).process(event)

    rows = journal.list_newest()
    assert len(rows) == 2
    follow = rows[0]
    assert follow.trigger is ShopListPublishTrigger.INVENTORY_ZERO
