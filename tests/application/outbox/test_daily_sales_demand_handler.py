from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest

from src.application.form_submissions import DeferredRetryOutboxError, NonRetryableOutboxError
from src.application.inventory_reconciliation.create_daily_sales_demands import (
    DailySalesDemandTransientError,
    IngestCursorNotReady,
    SellableCatalogNotReady,
    UnresolvedSellableCodesError,
)
from src.application.outbox.daily_sales_demand import DailySalesDemandHandler
from src.domain.ids import EventId
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.domain.machine_pnl.events import MachinePeriodPnlRequested

_SALES_DAY = date(2026, 8, 9)
_NOW = datetime(2026, 8, 10, 4, 0, tzinfo=UTC)
_RETRY_MINUTES = 15
_MAX_ATTEMPTS = 48


@dataclass(slots=True)
class _RecordingCreateDemands:
    calls: list[date] = field(default_factory=list)
    error: BaseException | None = None

    async def execute(self, *, sales_day: date) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append(sales_day)


def _handler(create: _RecordingCreateDemands) -> DailySalesDemandHandler:
    return DailySalesDemandHandler(
        create_demands=create,
        not_ready_retry_minutes=_RETRY_MINUTES,
        not_ready_max_attempts=_MAX_ATTEMPTS,
    )


def _requested() -> DailySalesDemandRequested:
    return DailySalesDemandRequested(
        event_id=EventId("daily_sales_demand:2026-08-09"),
        sales_day=_SALES_DAY,
        occurred_at=_NOW,
    )


def test_handler_maps_sales_day_to_use_case() -> None:
    create = _RecordingCreateDemands()
    handler = _handler(create)

    asyncio.run(handler.process(_requested()))

    assert create.calls == [_SALES_DAY]


def test_handler_maps_cursor_gate_to_deferred_retry() -> None:
    create = _RecordingCreateDemands(error=IngestCursorNotReady("cursor behind"))
    handler = _handler(create)

    with pytest.raises(DeferredRetryOutboxError) as ei:
        asyncio.run(handler.process(_requested()))

    err = ei.value
    assert err.delay == timedelta(minutes=_RETRY_MINUTES)
    assert err.max_attempts == _MAX_ATTEMPTS
    assert "cursor behind" in str(err)


def test_handler_maps_sellable_catalog_not_ready_to_deferred_retry() -> None:
    create = _RecordingCreateDemands(error=SellableCatalogNotReady("catalog empty"))
    handler = _handler(create)

    with pytest.raises(DeferredRetryOutboxError) as ei:
        asyncio.run(handler.process(_requested()))

    err = ei.value
    assert err.delay == timedelta(minutes=_RETRY_MINUTES)
    assert err.max_attempts == _MAX_ATTEMPTS
    assert "catalog empty" in str(err)


def test_handler_propagates_unresolved_sellable_as_non_retryable() -> None:
    err = UnresolvedSellableCodesError(frozenset({("W1", "X")}))
    create = _RecordingCreateDemands(error=err)
    handler = _handler(create)
    with pytest.raises(UnresolvedSellableCodesError):
        asyncio.run(handler.process(_requested()))
    assert isinstance(err, NonRetryableOutboxError)


def test_handler_propagates_transient_as_retryable() -> None:
    err = DailySalesDemandTransientError(frozenset({"S_MID"}))
    create = _RecordingCreateDemands(error=err)
    handler = _handler(create)
    with pytest.raises(DailySalesDemandTransientError):
        asyncio.run(handler.process(_requested()))
    assert not isinstance(err, NonRetryableOutboxError)


def test_handler_rejects_wrong_event_type() -> None:
    handler = _handler(_RecordingCreateDemands())
    wrong = MachinePeriodPnlRequested(
        event_id=EventId("x"),
        period_id="p",
        source_session_id="s",
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    with pytest.raises(NonRetryableOutboxError):
        asyncio.run(handler.process(wrong))
