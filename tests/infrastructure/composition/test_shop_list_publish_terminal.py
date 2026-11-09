from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from tests.application.product_identity.fakes import FakeDomainProductStore

from src.application.micromarket_loading.planogram import (
    MicromarketPlanogram,
    MicromarketPlanogramLine,
    MicromarketPlanogramShelf,
    SaveMicromarketPlanogram,
)
from src.application.micromarket_loading.publish_job import (
    enqueue_micromarket_shop_list_publish,
)
from src.application.micromarket_loading.shop_list import ShopListPublishStatus
from src.application.micromarket_loading.shop_list_publish_journal import (
    ShopListPublishJournalEntry,
    ShopListPublishJournalStatus,
)
from src.application.outbox.handler_ids import (
    MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID,
    REVISION_TELEGRAM_HANDLER_ID,
)
from src.application.product_identity import DomainProduct
from src.infrastructure.composition.adapters.shop_list_publish_terminal import (
    ShopListPublishTerminalNotifier,
)
from src.infrastructure.testing.micromarket_loading_fakes import (
    InMemoryMicromarketPlanogramStore,
    InMemoryShopListPublishJournal,
)


@dataclass
class _RecordingInner:
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def notify_terminal_failure(
        self,
        *,
        handler_id: str,
        event_document: dict[str, Any],
        error_message: str,
        entry_id: str | None = None,
        claim_id: str | None = None,
    ) -> None:
        self.calls.append(
            {
                "handler_id": handler_id,
                "event_document": event_document,
                "error_message": error_message,
                "entry_id": entry_id,
                "claim_id": claim_id,
            },
        )


class _Publisher:
    def publish(self, event: object) -> None:
        del event


def _publishing_store() -> InMemoryMicromarketPlanogramStore:
    store = InMemoryMicromarketPlanogramStore()
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
    SaveMicromarketPlanogram(
        store=store,
        catalog_codes={"2311"},
        products=products,
    ).execute(
        machine_code="701",
        shelves=(MicromarketPlanogramShelf(kit_group_id=6348, sort_order=0),),
        lines=[
            MicromarketPlanogramLine(
                product_code="",
                target_qty=1,
                price_rub=Decimal("10"),
                active=True,
                sort_order=0,
                kit_group_id=6348,
                domain_product_id="prod-1",
            ),
        ],
    )
    enqueue_micromarket_shop_list_publish(
        store=store,
        publisher=_Publisher(),
        machine_code="701",
        now=datetime(2026, 9, 25, tzinfo=UTC),
        products=products,
    )
    return store


def _event_document(*, publication_id: str, machine_code: str = "701") -> dict[str, Any]:
    return {
        "event_id": publication_id,
        "payload": {"machine_code": machine_code},
    }


def test_terminal_notifier_marks_publishing_failed_after_inner() -> None:
    store = _publishing_store()
    doc = store.get("701")
    assert doc is not None
    publication_id = doc.shop_list_publication_id
    assert publication_id
    journal = InMemoryShopListPublishJournal()
    journal.append(
        ShopListPublishJournalEntry(
            publication_id=publication_id,
            machine_code="701",
            status=ShopListPublishJournalStatus.RUNNING,
            created_at=datetime(2026, 9, 25, tzinfo=UTC),
            updated_at=datetime(2026, 9, 25, tzinfo=UTC),
        )
    )
    inner = _RecordingInner()
    notifier = ShopListPublishTerminalNotifier(
        inner=inner,
        store=store,
        journal=journal,
        now_factory=lambda: datetime(2026, 9, 25, 1, tzinfo=UTC),
    )

    asyncio.run(
        notifier.notify_terminal_failure(
            handler_id=MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID,
            event_document=_event_document(publication_id=publication_id),
            error_message="timeout",
        ),
    )

    assert len(inner.calls) == 1
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.FAILED
    assert updated.shop_list_error == "timeout"
    rows = journal.list_newest()
    assert len(rows) == 1
    assert rows[0].status is ShopListPublishJournalStatus.FAILED
    assert rows[0].error_message == "timeout"


def test_terminal_notifier_ignores_other_handler_id() -> None:
    store = _publishing_store()
    doc = store.get("701")
    assert doc is not None
    publication_id = doc.shop_list_publication_id
    assert publication_id
    inner = _RecordingInner()
    notifier = ShopListPublishTerminalNotifier(inner=inner, store=store)

    asyncio.run(
        notifier.notify_terminal_failure(
            handler_id=REVISION_TELEGRAM_HANDLER_ID,
            event_document=_event_document(publication_id=publication_id),
            error_message="timeout",
        ),
    )

    assert len(inner.calls) == 1
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHING


def test_terminal_notifier_does_not_clobber_published() -> None:
    store = _publishing_store()
    doc = store.get("701")
    assert doc is not None
    publication_id = doc.shop_list_publication_id
    assert publication_id
    store.upsert(
        MicromarketPlanogram(
            machine_code=doc.machine_code,
            lines=doc.lines,
            updated_at=doc.updated_at,
            shop_list_status=ShopListPublishStatus.PUBLISHED,
            shop_list_publication_id=publication_id,
        ),
    )
    inner = _RecordingInner()
    notifier = ShopListPublishTerminalNotifier(inner=inner, store=store)

    asyncio.run(
        notifier.notify_terminal_failure(
            handler_id=MICROMARKET_SHOP_LIST_PUBLISH_HANDLER_ID,
            event_document=_event_document(publication_id=publication_id),
            error_message="timeout",
        ),
    )

    assert len(inner.calls) == 1
    updated = store.get("701")
    assert updated is not None
    assert updated.shop_list_status is ShopListPublishStatus.PUBLISHED
    assert updated.shop_list_error == ""
