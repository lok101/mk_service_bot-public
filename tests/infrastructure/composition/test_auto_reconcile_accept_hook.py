from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.form_submissions import FormSubmissionRejectedError
from src.application.outbox.handler_ids import SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID
from src.domain.form_submission import FormAnswer
from src.domain.form_tokens import TechnicianWarehouseInventoryTokenPayload
from src.domain.ids import EventId, TechnicianId
from src.domain.technician_settlement.portion_events import SettlementPortionSyncTransfersRequested
from src.domain.technician_warehouse.events import TechnicianWarehouseInventoryCounted
from src.infrastructure.composition.adapters.auto_reconcile_accept_hook import (
    AcceptWithAutoReconcileEnqueue,
)
from src.infrastructure.outbox.memory import InMemoryOutboxStore
from src.infrastructure.testing.technician_warehouse_fakes import (
    InMemoryTechnicianWarehouseEventStore,
    InMemoryTechnicianWarehouseRepository,
)

_TECH = TechnicianId("t1")
_COUNTED_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


@dataclass
class _RecordingAccept:
    calls: int = 0
    event: TechnicianWarehouseInventoryCounted | None = None

    def execute(
        self,
        *,
        form_id: str,
        submitted_at: datetime,
        form_token: str,
        token_payload: TechnicianWarehouseInventoryTokenPayload,
        answers: tuple[FormAnswer, ...],
    ) -> TechnicianWarehouseInventoryCounted:
        del form_id, submitted_at, form_token, token_payload, answers
        self.calls += 1
        assert self.event is not None
        return self.event


@dataclass
class _RecordingPublisher:
    events: list[object] = field(default_factory=list)

    def publish(self, event: object) -> None:
        self.events.append(event)


def _token_payload() -> TechnicianWarehouseInventoryTokenPayload:
    return TechnicianWarehouseInventoryTokenPayload(
        technician_id=_TECH,
        issued_at=_COUNTED_AT,
        nonce="n1",
    )


def _inventory_event(*, baseline: bool = False) -> TechnicianWarehouseInventoryCounted:
    return TechnicianWarehouseInventoryCounted(
        event_id=EventId("wh-inv-1"),
        technician_id=_TECH,
        occurred_at=_COUNTED_AT,
        inventory_id="inv1",
        form_token="tok-1",
        counted_at=_COUNTED_AT,
        lines=(("sku-a", Decimal("1")),),
        baseline=baseline,
    )


def _open_repo() -> InMemoryTechnicianWarehouseRepository:
    return InMemoryTechnicianWarehouseRepository(
        event_store=InMemoryTechnicianWarehouseEventStore(),
    )


def _closed_repo() -> InMemoryTechnicianWarehouseRepository:
    repo = _open_repo()
    warehouse = repo.get(_TECH)
    warehouse.close_exit(
        closed_at=_COUNTED_AT,
        return_external_document_id="ret-1",
        return_content_hash="hash-1",
    )
    repo.save(warehouse, expected_version=0)
    return repo


def _wrapper(
    *,
    enabled: bool = True,
    store: InMemoryOutboxStore | None = None,
    inner: _RecordingAccept | None = None,
    publisher: _RecordingPublisher | None = None,
    warehouse_repository: InMemoryTechnicianWarehouseRepository | None = None,
) -> tuple[
    AcceptWithAutoReconcileEnqueue,
    _RecordingAccept,
    _RecordingPublisher,
    InMemoryOutboxStore,
]:
    resolved_inner = inner or _RecordingAccept(event=_inventory_event())
    resolved_publisher = publisher or _RecordingPublisher()
    resolved_store = store or InMemoryOutboxStore()
    wrapper = AcceptWithAutoReconcileEnqueue(
        inner=resolved_inner,
        outbox_store=resolved_store,
        publisher=resolved_publisher,
        auto_reconcile_enabled=enabled,
        warehouse_repository=warehouse_repository or _open_repo(),
    )
    return wrapper, resolved_inner, resolved_publisher, resolved_store


def test_portion_lock_rejects_accept_while_active() -> None:
    store = InMemoryOutboxStore()
    store.enqueue(
        event_id="portion:t1:inv0:sync",
        handler_id=SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
        event_document={"event_id": "portion:t1:inv0:sync"},
    )
    wrapper, inner, _publisher, _store = _wrapper(store=store)

    with pytest.raises(FormSubmissionRejectedError, match="active settlement portion"):
        wrapper.execute(
            form_id="form-1",
            submitted_at=_COUNTED_AT,
            form_token="tok-new",
            token_payload=_token_payload(),
            answers=(),
        )

    assert inner.calls == 0


def test_portion_lock_cleared_after_terminal() -> None:
    store = InMemoryOutboxStore()
    store.enqueue(
        event_id="portion:t1:inv0:sync",
        handler_id=SETTLEMENT_PORTION_SYNC_TRANSFERS_HANDLER_ID,
        event_document={"event_id": "portion:t1:inv0:sync"},
    )
    claimed = store.claim_pending(limit=1)
    entry = claimed[0]
    assert store.mark_processed(entry["entry_id"], claim_id=str(entry["claim_id"]))

    wrapper, inner, publisher, _store = _wrapper(store=store)
    event = wrapper.execute(
        form_id="form-1",
        submitted_at=_COUNTED_AT,
        form_token="tok-new",
        token_payload=_token_payload(),
        answers=(),
    )

    assert inner.calls == 1
    assert event.inventory_id == "inv1"
    assert len(publisher.events) == 1
    assert isinstance(publisher.events[0], SettlementPortionSyncTransfersRequested)


def test_enqueue_sync_after_accept_when_enabled() -> None:
    wrapper, inner, publisher, _store = _wrapper(enabled=True)

    event = wrapper.execute(
        form_id="form-1",
        submitted_at=_COUNTED_AT,
        form_token="tok-new",
        token_payload=_token_payload(),
        answers=(),
    )

    assert inner.calls == 1
    assert event.baseline is False
    assert len(publisher.events) == 1
    published = publisher.events[0]
    assert isinstance(published, SettlementPortionSyncTransfersRequested)
    assert published.event_id.value == "portion:t1:inv1:sync"
    assert published.technician_id == _TECH
    assert published.warehouse_inventory_id == "inv1"
    assert published.warehouse_inventory_moment == _COUNTED_AT


def test_enqueue_skipped_when_disabled() -> None:
    wrapper, inner, publisher, _store = _wrapper(enabled=False)

    event = wrapper.execute(
        form_id="form-1",
        submitted_at=_COUNTED_AT,
        form_token="tok-new",
        token_payload=_token_payload(),
        answers=(),
    )

    assert inner.calls == 1
    assert event.inventory_id == "inv1"
    assert publisher.events == []


def test_enqueue_skipped_when_warehouse_closed() -> None:
    wrapper, inner, publisher, _store = _wrapper(
        enabled=True,
        warehouse_repository=_closed_repo(),
    )

    event = wrapper.execute(
        form_id="form-1",
        submitted_at=_COUNTED_AT,
        form_token="tok-new",
        token_payload=_token_payload(),
        answers=(),
    )

    assert inner.calls == 1
    assert event.inventory_id == "inv1"
    assert publisher.events == []
