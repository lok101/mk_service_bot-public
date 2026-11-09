from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from src.application.form_submissions.outbox_errors import DeferredRetryOutboxError
from src.application.inventory_reconciliation import VerifyPortionSalesHoldingError
from src.application.outbox.settlement_portion_sales_verify import (
    SettlementPortionSalesVerifyHandler,
)
from src.domain.events import DomainEvent
from src.domain.ids import EventId, TechnicianId
from src.domain.technician_settlement.portion_events import (
    SettlementPortionReconcileRequested,
    SettlementPortionSalesVerifyRequested,
)

_TECH = TechnicianId("t1")
_INV_ID = "inv1"
_MOMENT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


@dataclass
class _FakeVerifier:
    raises: Exception | None = None
    calls: list[tuple[TechnicianId, datetime]] = field(default_factory=list)

    def execute(
        self,
        *,
        technician_id: TechnicianId,
        cutoff: datetime,
    ) -> object:
        self.calls.append((technician_id, cutoff))
        if self.raises is not None:
            raise self.raises
        return {"ok": True}


@dataclass
class _CapturingPublisher:
    events: list[DomainEvent] = field(default_factory=list)

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


def _sales_event() -> SettlementPortionSalesVerifyRequested:
    return SettlementPortionSalesVerifyRequested(
        event_id=EventId("portion:t1:inv1:sales"),
        technician_id=_TECH,
        warehouse_inventory_id=_INV_ID,
        warehouse_inventory_moment=_MOMENT,
        occurred_at=_MOMENT,
    )


def test_sales_verify_handler_enqueues_reconcile_on_success() -> None:
    verifier = _FakeVerifier()
    publisher = _CapturingPublisher()
    handler = SettlementPortionSalesVerifyHandler(
        verifier=verifier,
        publisher=publisher,
    )

    asyncio.run(handler.process(_sales_event()))

    assert verifier.calls == [(_TECH, _MOMENT)]
    assert len(publisher.events) == 1
    nxt = publisher.events[0]
    assert isinstance(nxt, SettlementPortionReconcileRequested)
    assert nxt.event_id.value.endswith(":reconcile")
    assert nxt.event_id.value == "portion:t1:inv1:reconcile"
    assert nxt.warehouse_inventory_id == _INV_ID


def test_sales_verify_handler_holding_does_not_enqueue_reconcile() -> None:
    verifier = _FakeVerifier(raises=VerifyPortionSalesHoldingError("holding"))
    publisher = _CapturingPublisher()
    handler = SettlementPortionSalesVerifyHandler(
        verifier=verifier,
        publisher=publisher,
    )

    with pytest.raises(VerifyPortionSalesHoldingError):
        asyncio.run(handler.process(_sales_event()))

    assert publisher.events == []


class KitVendingNetworkError(Exception):
    pass


class KitVendingResponseError(Exception):
    def __init__(self, message: str, result_code: int) -> None:
        self.result_code = result_code
        super().__init__(message)


def test_sales_verify_handler_network_error_is_deferred_retry() -> None:
    # error → retryable deferred
    verifier = _FakeVerifier(raises=KitVendingNetworkError("timeout"))
    publisher = _CapturingPublisher()
    handler = SettlementPortionSalesVerifyHandler(
        verifier=verifier,
        publisher=publisher,
    )
    with pytest.raises(DeferredRetryOutboxError) as ei:
        asyncio.run(handler.process(_sales_event()))
    assert publisher.events == []
    assert ei.value.delay == timedelta(seconds=60)
    assert ei.value.max_attempts is None


def test_sales_verify_handler_result_code_1_is_deferred_retry() -> None:
    # error: ResultCode=1
    verifier = _FakeVerifier(
        raises=KitVendingResponseError("temporarily unavailable", result_code=1),
    )
    publisher = _CapturingPublisher()
    handler = SettlementPortionSalesVerifyHandler(
        verifier=verifier,
        publisher=publisher,
    )
    with pytest.raises(DeferredRetryOutboxError):
        asyncio.run(handler.process(_sales_event()))
    assert publisher.events == []


def test_sales_verify_handler_other_result_code_propagates() -> None:
    # edge: не расширять 14/прочее
    exc = KitVendingResponseError("invalid request id", result_code=14)
    verifier = _FakeVerifier(raises=exc)
    publisher = _CapturingPublisher()
    handler = SettlementPortionSalesVerifyHandler(
        verifier=verifier,
        publisher=publisher,
    )
    with pytest.raises(KitVendingResponseError) as ei:
        asyncio.run(handler.process(_sales_event()))
    assert ei.value.result_code == 14
    assert publisher.events == []


def test_sales_verify_handler_enqueues_reconcile_with_quarantine_not_before() -> None:
    # happy: quarantine_seconds > 0 → not_before ~= now + quarantine_seconds
    verifier = _FakeVerifier()
    publisher = _CapturingPublisher()
    handler = SettlementPortionSalesVerifyHandler(
        verifier=verifier,
        publisher=publisher,
        quarantine_seconds=3600,
    )
    before = datetime.now(tz=UTC)

    asyncio.run(handler.process(_sales_event()))

    nxt = publisher.events[0]
    assert isinstance(nxt, SettlementPortionReconcileRequested)
    assert nxt.not_before is not None
    delta = nxt.not_before - before
    assert timedelta(minutes=59) <= delta <= timedelta(minutes=61)


def test_sales_verify_handler_zero_quarantine_enqueues_without_not_before() -> None:
    # edge / regression: quarantine_seconds default (0) → not_before None
    verifier = _FakeVerifier()
    publisher = _CapturingPublisher()
    handler = SettlementPortionSalesVerifyHandler(
        verifier=verifier,
        publisher=publisher,
    )

    asyncio.run(handler.process(_sales_event()))

    nxt = publisher.events[0]
    assert isinstance(nxt, SettlementPortionReconcileRequested)
    assert nxt.not_before is None


def test_sales_verify_logs_enqueue_reconcile_not_before(
    caplog: pytest.LogCaptureFixture,
) -> None:
    verifier = _FakeVerifier()
    publisher = _CapturingPublisher()
    handler = SettlementPortionSalesVerifyHandler(
        verifier=verifier,
        publisher=publisher,
        quarantine_seconds=3600,
    )
    caplog.set_level(logging.INFO)

    asyncio.run(handler.process(_sales_event()))

    records = [
        record
        for record in caplog.records
        if "settlement_portion_reconcile_enqueued" in record.getMessage()
    ]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "technician_id=t1" in message
    assert "warehouse_inventory_id=inv1" in message
    assert "not_before=" in message
    nxt = publisher.events[0]
    assert isinstance(nxt, SettlementPortionReconcileRequested)
    assert nxt.not_before is not None
    assert nxt.not_before.isoformat() in message
