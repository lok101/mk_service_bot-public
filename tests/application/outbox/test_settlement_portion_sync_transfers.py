from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from src.application.outbox.border_unregistered_ops import (
    DedupingBorderUnregisteredOpsAlerter,
)
from src.application.outbox.finalized_transfer_drift_ops import (
    DedupingFinalizedTransferDriftOpsAlerter,
)
from src.application.outbox.settlement_portion_sync_transfers import (
    SettlementPortionSyncTransfersHandler,
)
from src.application.technician_warehouse import (
    IgnoredFinalizedTransfer,
    MoySkladUnavailable,
    TechnicianWarehouseImportBlocked,
    TechnicianWarehouseImportResult,
)
from src.domain.events import DomainEvent
from src.domain.ids import EventId, TechnicianId
from src.domain.technician_settlement.portion_events import (
    SettlementPortionSalesVerifyRequested,
    SettlementPortionSyncTransfersRequested,
)

_TECH = TechnicianId("t1")
_INV_ID = "inv1"
_MOMENT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
_EMPTY_RESULT = TechnicianWarehouseImportResult(
    imported=0,
    updated=0,
    voided=0,
    ignored=0,
    skipped_unresolved=0,
    truncated_non_domain=0,
    transfer_refs=(),
    unmatched_products=(),
)


@dataclass
class _FakeImporter:
    raises: Exception | None = None
    result: TechnicianWarehouseImportResult = _EMPTY_RESULT
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)

    async def execute(
        self,
        technician_id: TechnicianId,
        *,
        anchor_at: datetime,
    ) -> TechnicianWarehouseImportResult:
        self.calls.append((technician_id, anchor_at))
        if self.raises is not None:
            raise self.raises
        return self.result


@dataclass
class _CapturingPublisher:
    events: list[DomainEvent] = field(default_factory=list)

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def _sync_event() -> SettlementPortionSyncTransfersRequested:
    return SettlementPortionSyncTransfersRequested(
        event_id=EventId("portion:t1:inv1:sync"),
        technician_id=_TECH,
        warehouse_inventory_id=_INV_ID,
        warehouse_inventory_moment=_MOMENT,
        occurred_at=_MOMENT,
    )


def test_sync_success_enqueues_sales_verify() -> None:
    importer = _FakeImporter()
    publisher = _CapturingPublisher()
    handler = SettlementPortionSyncTransfersHandler(
        importer=importer,
        publisher=publisher,
    )

    asyncio.run(handler.process(_sync_event()))

    assert importer.calls == [(_TECH, _MOMENT)]
    assert len(publisher.events) == 1
    nxt = publisher.events[0]
    assert isinstance(nxt, SettlementPortionSalesVerifyRequested)
    assert nxt.event_id.value == "portion:t1:inv1:sales"
    assert nxt.warehouse_inventory_id == _INV_ID


def test_sync_fail_does_not_enqueue_sales() -> None:
    importer = _FakeImporter(raises=MoySkladUnavailable("down"))
    publisher = _CapturingPublisher()
    handler = SettlementPortionSyncTransfersHandler(
        importer=importer,
        publisher=publisher,
    )

    with pytest.raises(MoySkladUnavailable):
        asyncio.run(handler.process(_sync_event()))

    assert publisher.events == []


@dataclass
class _RecordingBorderAlerter:
    calls: list[tuple[str, tuple[tuple[str, str], ...]]] = field(default_factory=list)

    def notify_unregistered(
        self,
        *,
        technician_id: str,
        products: tuple[tuple[str, str], ...],
    ) -> None:
        self.calls.append((technician_id, products))


def test_unregistered_border_notifies_ops_and_reraises() -> None:
    products = (("10165", "Молоко"), ("10078", "Сироп"))
    importer = _FakeImporter(
        raises=TechnicianWarehouseImportBlocked(
            "unregistered",
            technician_id="t1",
            unregistered_products=products,
        ),
    )
    publisher = _CapturingPublisher()
    alerter = _RecordingBorderAlerter()
    handler = SettlementPortionSyncTransfersHandler(
        importer=importer,
        publisher=publisher,
        border_ops_alerter=DedupingBorderUnregisteredOpsAlerter(inner=alerter),
    )

    with pytest.raises(TechnicianWarehouseImportBlocked):
        asyncio.run(handler.process(_sync_event()))
    with pytest.raises(TechnicianWarehouseImportBlocked):
        asyncio.run(handler.process(_sync_event()))

    assert alerter.calls == [("t1", products)]
    assert publisher.events == []


def test_import_blocked_without_border_products_skips_alerter() -> None:
    importer = _FakeImporter(
        raises=TechnicianWarehouseImportBlocked("TECHNICIAN_WAREHOUSE_SUPPLY_STORE_CODES"),
    )
    publisher = _CapturingPublisher()
    alerter = _RecordingBorderAlerter()
    handler = SettlementPortionSyncTransfersHandler(
        importer=importer,
        publisher=publisher,
        border_ops_alerter=alerter,
    )

    with pytest.raises(TechnicianWarehouseImportBlocked):
        asyncio.run(handler.process(_sync_event()))

    assert alerter.calls == []


@dataclass
class _RecordingDriftAlerter:
    calls: list[tuple[str, tuple[IgnoredFinalizedTransfer, ...]]] = field(default_factory=list)
    fail: bool = False

    def notify_drift(
        self,
        *,
        technician_id: str,
        items: tuple[IgnoredFinalizedTransfer, ...],
    ) -> None:
        if self.fail:
            raise RuntimeError("telegram down")
        self.calls.append((technician_id, items))


def test_ignored_finalized_notifies_ops_and_continues() -> None:
    items = (IgnoredFinalizedTransfer(external_document_id="move-1", kind="changed"),)
    result = TechnicianWarehouseImportResult(
        imported=0,
        updated=0,
        voided=0,
        ignored=1,
        skipped_unresolved=0,
        truncated_non_domain=0,
        transfer_refs=(),
        unmatched_products=(),
        ignored_finalized_transfers=items,
    )
    importer = _FakeImporter(result=result)
    publisher = _CapturingPublisher()
    alerter = _RecordingDriftAlerter()
    handler = SettlementPortionSyncTransfersHandler(
        importer=importer,
        publisher=publisher,
        drift_ops_alerter=DedupingFinalizedTransferDriftOpsAlerter(inner=alerter),
    )

    asyncio.run(handler.process(_sync_event()))
    asyncio.run(handler.process(_sync_event()))

    assert alerter.calls == [("t1", items)]
    assert len(publisher.events) == 2


def test_drift_alerter_failure_does_not_block_sync() -> None:
    items = (IgnoredFinalizedTransfer(external_document_id="move-1", kind="missing"),)
    result = TechnicianWarehouseImportResult(
        imported=0,
        updated=0,
        voided=0,
        ignored=1,
        skipped_unresolved=0,
        truncated_non_domain=0,
        transfer_refs=(),
        unmatched_products=(),
        ignored_finalized_transfers=items,
    )
    importer = _FakeImporter(result=result)
    publisher = _CapturingPublisher()
    handler = SettlementPortionSyncTransfersHandler(
        importer=importer,
        publisher=publisher,
        drift_ops_alerter=_RecordingDriftAlerter(fail=True),
    )

    asyncio.run(handler.process(_sync_event()))

    assert len(publisher.events) == 1
