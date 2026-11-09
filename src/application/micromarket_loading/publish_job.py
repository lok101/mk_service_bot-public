from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from beartype import beartype

from src.application.micromarket_loading.planogram import MicromarketPlanogram
from src.application.micromarket_loading.ports import (
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
)
from src.application.micromarket_loading.publishable_snapshot import (
    build_publishable_snapshot,
)
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.micromarket_loading.shop_list_intended import (
    build_shop_list_intended_lines,
)
from src.application.micromarket_loading.shop_list_publish_journal import (
    SUPERSEDED_BY_NEWER_PUBLISH_RU,
    ShopListLastSucceededSnapshot,
    ShopListPublishJournalEntry,
    ShopListPublishJournalStatus,
    ShopListPublishTrigger,
    diff_shop_list_intended,
)
from src.application.product_identity.ports import DomainProductStore
from src.domain.ids import EventId
from src.domain.micromarket_loading.publish_event import MicromarketShopListPublishRequested


@beartype
@dataclass(frozen=True, slots=True)
class Enqueued:
    publication_id: str
    skipped_names: tuple[str, ...] = ()


@beartype
@dataclass(frozen=True, slots=True)
class AlreadyPublishing:
    pass


@beartype
@dataclass(frozen=True, slots=True)
class MissingGroup:
    product_code: str


@beartype
@dataclass(frozen=True, slots=True)
class NothingToSend:
    skipped_names: tuple[str, ...] = ()


@beartype
@dataclass(frozen=True, slots=True)
class PriceRequired:
    product_code: str


EnqueueShopListResult = Enqueued | AlreadyPublishing | MissingGroup | NothingToSend | PriceRequired


@runtime_checkable
class ShopListPublishEventPublisher(Protocol):
    def publish(self, event: MicromarketShopListPublishRequested) -> None: ...


@beartype
def enqueue_micromarket_shop_list_publish(
    *,
    store: MicromarketPlanogramStore,
    publisher: ShopListPublishEventPublisher,
    machine_code: str,
    now: datetime,
    products: DomainProductStore | None = None,
    stock_store: MicromarketDeviceStockStore | None = None,
    journal: ShopListPublishJournal | None = None,
    trigger: ShopListPublishTrigger | None = None,
    baseline_store: ShopListLastSucceededSnapshotStore | None = None,
) -> EnqueueShopListResult:
    doc = store.get(machine_code)
    if doc is None:
        raise ValueError(f"planogram not found for machine_code={machine_code!r}")
    if doc.shop_list_status is ShopListPublishStatus.PUBLISHING:
        if not doc.shop_list_catch_up_requested:
            store.upsert(
                MicromarketPlanogram(
                    machine_code=doc.machine_code,
                    lines=doc.lines,
                    updated_at=doc.updated_at,
                    shop_list_status=doc.shop_list_status,
                    shop_list_error=doc.shop_list_error,
                    shop_list_publication_id=doc.shop_list_publication_id,
                    shop_list_catch_up_requested=True,
                    shelves=doc.shelves,
                ),
            )
        return AlreadyPublishing()
    stock = stock_store.load(machine_code) if stock_store is not None else None
    snapshot = build_publishable_snapshot(doc, products, stock=stock)
    if not snapshot.lines and doc.lines:
        return NothingToSend(skipped_names=snapshot.skipped_names)
    for line in doc.lines:
        if not line.active:
            continue
        if line.price_rub < 1 or line.price_rub != line.price_rub.to_integral_value():
            code = line.product_code.strip() or (line.domain_product_id or "").strip() or "?"
            return PriceRequired(product_code=code)
    for entry in snapshot.lines:
        if entry.kit_group_id is None:
            return MissingGroup(product_code=entry.product_code)
    publication_id = uuid.uuid4().hex
    lines = tuple(
        (
            entry.product_code,
            str(entry.price_rub),
            int(entry.kit_group_id),
            entry.disabled,
        )
        for entry in snapshot.lines
        if entry.kit_group_id is not None
    )
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=doc.lines,
            updated_at=doc.updated_at,
            shop_list_status=ShopListPublishStatus.PUBLISHING,
            shop_list_error="",
            shop_list_publication_id=publication_id,
            shop_list_catch_up_requested=False,
            shelves=doc.shelves,
        ),
    )
    try:
        publisher.publish(
            MicromarketShopListPublishRequested(
                event_id=EventId(publication_id),
                machine_code=doc.machine_code,
                publication_id=publication_id,
                lines=lines,
                occurred_at=now,
            ),
        )
    except Exception:
        store.upsert(doc)
        raise
    if journal is not None:
        resolved_trigger = trigger if trigger is not None else ShopListPublishTrigger.MANUAL
        intended = build_shop_list_intended_lines(doc, products, stock=stock)
        baseline = baseline_store.get(doc.machine_code) if baseline_store is not None else None
        baseline_lines = None if baseline is None else baseline.lines
        effects = diff_shop_list_intended(baseline_lines, intended)
        _fail_prior_running_journal_entries(
            journal,
            machine_code=doc.machine_code,
            now=now,
        )
        journal.append(
            ShopListPublishJournalEntry(
                publication_id=publication_id,
                machine_code=doc.machine_code,
                status=ShopListPublishJournalStatus.RUNNING,
                created_at=now,
                updated_at=now,
                trigger=resolved_trigger,
                effects=effects,
                intended_lines=intended,
                baseline_lines=() if baseline_lines is None else baseline_lines,
            ),
        )
    return Enqueued(
        publication_id=publication_id,
        skipped_names=snapshot.skipped_names,
    )


@beartype
def _fail_prior_running_journal_entries(
    journal: ShopListPublishJournal,
    *,
    machine_code: str,
    now: datetime,
) -> None:
    for entry in journal.list_newest():
        if entry.machine_code != machine_code:
            continue
        if entry.status is not ShopListPublishJournalStatus.RUNNING:
            continue
        journal.update_by_publication_id(
            entry.publication_id,
            status=ShopListPublishJournalStatus.FAILED,
            error_message=SUPERSEDED_BY_NEWER_PUBLISH_RU,
            now=now,
        )


@beartype
@dataclass(frozen=True, slots=True)
class Synced:
    pass


@beartype
@dataclass(frozen=True, slots=True)
class PreflightFailed:
    message: str


@beartype
@dataclass(frozen=True, slots=True)
class CommandRejected:
    message: str


@beartype
@dataclass(frozen=True, slots=True)
class TemplateWriteFailed:
    message: str


@beartype
@dataclass(frozen=True, slots=True)
class SnapshotStale:
    pass


SyncSnapshotResult = (
    Synced | PreflightFailed | CommandRejected | TemplateWriteFailed | SnapshotStale
)


@runtime_checkable
class ShopListMatrixGateway(Protocol):
    def sync_snapshot(
        self,
        *,
        machine_code: str,
        lines: tuple[tuple[str, str, int, bool], ...],
        snapshot_still_current: Callable[[], bool],
        catalog_names: tuple[tuple[str, str], ...] = (),
    ) -> SyncSnapshotResult: ...


@beartype
def mark_shop_list_publication_failed(
    store: MicromarketPlanogramStore,
    publication_id: str,
    error_message: str,
    *,
    machine_code: str | None = None,
    journal: ShopListPublishJournal | None = None,
    now: datetime | None = None,
) -> None:
    doc = _resolve_by_publication_id(store, publication_id, machine_code=machine_code)
    if doc is None:
        return
    if doc.shop_list_publication_id != publication_id:
        return
    if doc.shop_list_status is ShopListPublishStatus.PUBLISHED:
        return
    if doc.shop_list_status is not ShopListPublishStatus.PUBLISHING:
        return
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=doc.lines,
            updated_at=doc.updated_at,
            shop_list_status=ShopListPublishStatus.FAILED,
            shop_list_error=error_message,
            shop_list_publication_id=doc.shop_list_publication_id,
            shop_list_catch_up_requested=doc.shop_list_catch_up_requested,
            shelves=doc.shelves,
        ),
    )
    if journal is not None:
        journal.update_by_publication_id(
            publication_id,
            status=ShopListPublishJournalStatus.FAILED,
            error_message=error_message,
            now=now if now is not None else datetime.now(UTC),
        )


def _resolve_by_publication_id(
    store: MicromarketPlanogramStore,
    publication_id: str,
    *,
    machine_code: str | None,
) -> MicromarketPlanogram | None:
    if machine_code is not None:
        return store.get(machine_code)
    mapping = getattr(store, "_by_machine", None)
    if isinstance(mapping, dict):
        for candidate in mapping.values():
            if (
                isinstance(candidate, MicromarketPlanogram)
                and candidate.shop_list_publication_id == publication_id
            ):
                return candidate
    return None


@beartype
@dataclass(frozen=True, slots=True)
class MicromarketShopListPublishHandler:
    store: MicromarketPlanogramStore
    gateway: ShopListMatrixGateway
    products: DomainProductStore | None = None
    stock_store: MicromarketDeviceStockStore | None = None
    event_publisher: ShopListPublishEventPublisher | None = None
    journal: ShopListPublishJournal | None = None
    baseline_store: ShopListLastSucceededSnapshotStore | None = None
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC)

    def process(self, event: MicromarketShopListPublishRequested) -> None:
        doc = self.store.get(event.machine_code)
        if doc is None:
            return
        if doc.shop_list_publication_id != event.publication_id:
            return
        if doc.shop_list_status is ShopListPublishStatus.PUBLISHED:
            return
        if doc.shop_list_status is ShopListPublishStatus.FAILED:
            self._set_status(doc, ShopListPublishStatus.PUBLISHING, "")
            self._mark_journal(
                event.publication_id,
                status=ShopListPublishJournalStatus.RUNNING,
            )
            resumed = self.store.get(event.machine_code)
            if resumed is None or resumed.shop_list_publication_id != event.publication_id:
                return
            doc = resumed

        def snapshot_still_current() -> bool:
            current = self.store.get(event.machine_code)
            if current is None:
                return False
            if current.shop_list_publication_id != event.publication_id:
                return False
            if current.shop_list_catch_up_requested:
                return True
            stock = (
                self.stock_store.load(event.machine_code) if self.stock_store is not None else None
            )
            snapshot = build_publishable_snapshot(current, self.products, stock=stock)
            current_lines = tuple(
                (
                    entry.product_code,
                    str(entry.price_rub),
                    int(entry.kit_group_id),
                    entry.disabled,
                )
                for entry in snapshot.lines
                if entry.kit_group_id is not None
            )
            return current_lines == event.lines

        catalog_names = self._catalog_names_for_snapshot(doc, event.lines)
        result = self.gateway.sync_snapshot(
            machine_code=event.machine_code,
            lines=event.lines,
            snapshot_still_current=snapshot_still_current,
            catalog_names=catalog_names,
        )
        latest = self.store.get(event.machine_code)
        if latest is None or latest.shop_list_publication_id != event.publication_id:
            return
        if isinstance(result, Synced):
            self._set_status(latest, ShopListPublishStatus.PUBLISHED, "")
            self._mark_journal(
                event.publication_id,
                status=ShopListPublishJournalStatus.SUCCEEDED,
                machine_code=event.machine_code,
            )
        elif isinstance(result, CommandRejected):
            message = result.message or "База товаров на терминал не ушла"
            self._set_status(latest, ShopListPublishStatus.FAILED, message)
            self._mark_journal(
                event.publication_id,
                status=ShopListPublishJournalStatus.FAILED,
                error_message=message,
            )
        elif isinstance(result, SnapshotStale):
            message = "Планограмма изменилась во время публикации"
            self._set_status(latest, ShopListPublishStatus.FAILED, message)
            self._mark_journal(
                event.publication_id,
                status=ShopListPublishJournalStatus.FAILED,
                error_message=message,
            )
        elif isinstance(result, (PreflightFailed, TemplateWriteFailed)):
            self._set_status(latest, ShopListPublishStatus.FAILED, result.message)
            self._mark_journal(
                event.publication_id,
                status=ShopListPublishJournalStatus.FAILED,
                error_message=result.message,
            )
        else:
            return
        self._maybe_enqueue_catch_up(event.machine_code)

    def _catalog_names_for_snapshot(
        self,
        doc: MicromarketPlanogram,
        lines: tuple[tuple[str, str, int, bool], ...],
    ) -> tuple[tuple[str, str], ...]:
        names_by_number: dict[str, str] = {}
        if self.products is not None:
            for line in doc.lines:
                if not line.domain_product_id:
                    continue
                product = self.products.get(line.domain_product_id)
                if product is None:
                    continue
                names_by_number[product.number] = product.name
        return tuple(
            (product_code, names_by_number.get(product_code, ""))
            for product_code, _price, _group, _disabled in lines
        )

    def _set_status(
        self,
        doc: MicromarketPlanogram,
        status: ShopListPublishStatus,
        error: str,
    ) -> None:
        self.store.upsert(
            MicromarketPlanogram(
                machine_code=doc.machine_code,
                lines=doc.lines,
                updated_at=doc.updated_at,
                shop_list_status=status,
                shop_list_error=error,
                shop_list_publication_id=doc.shop_list_publication_id,
                shop_list_catch_up_requested=doc.shop_list_catch_up_requested,
                shelves=doc.shelves,
            ),
        )

    def _mark_journal(
        self,
        publication_id: str,
        *,
        status: ShopListPublishJournalStatus,
        error_message: str = "",
        machine_code: str = "",
    ) -> None:
        if self.journal is None:
            return
        now = self.now_factory()
        if (
            status is ShopListPublishJournalStatus.SUCCEEDED
            and self.baseline_store is not None
            and machine_code
        ):
            matched: ShopListPublishJournalEntry | None = None
            for entry in self.journal.list_newest():
                if entry.publication_id == publication_id:
                    matched = entry
                    break
            if matched is not None:
                self.baseline_store.upsert(
                    ShopListLastSucceededSnapshot(
                        machine_code=machine_code,
                        lines=matched.intended_lines,
                        updated_at=now,
                    )
                )
        self.journal.update_by_publication_id(
            publication_id,
            status=status,
            error_message=error_message,
            now=now,
        )

    def _maybe_enqueue_catch_up(self, machine_code: str) -> None:
        if self.event_publisher is None:
            return
        latest = self.store.get(machine_code)
        if latest is None or not latest.shop_list_catch_up_requested:
            return
        if latest.shop_list_status is ShopListPublishStatus.PUBLISHING:
            return
        catch_up_trigger = ShopListPublishTrigger.MANUAL
        if self.journal is not None and latest.shop_list_publication_id:
            for entry in self.journal.list_newest():
                if entry.publication_id == latest.shop_list_publication_id:
                    catch_up_trigger = (
                        entry.trigger
                        if entry.trigger is not None
                        else ShopListPublishTrigger.MANUAL
                    )
                    break
        enqueue_micromarket_shop_list_publish(
            store=self.store,
            publisher=self.event_publisher,
            machine_code=machine_code,
            now=self.now_factory(),
            products=self.products,
            stock_store=self.stock_store,
            journal=self.journal,
            trigger=catch_up_trigger,
            baseline_store=self.baseline_store,
        )
