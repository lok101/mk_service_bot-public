from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from tests.application.inventory_reconciliation.sellable_fakes import (
    MappingSellableProductCodeCatalog,
)

from src.application.form_submissions import DeferredRetryOutboxError, NonRetryableOutboxError
from src.application.inventory_reconciliation.create_daily_sales_demands import (
    CreateDailySalesDemands,
    IngestCursorNotReady,
    UnresolvedSellableCodesError,
)
from src.application.inventory_reconciliation.ms_registrar_ports import (
    RegistrarPermanentError,
)
from src.application.outbox.daily_sales_demand import DailySalesDemandHandler
from src.application.outbox.handler_ids import DAILY_SALES_DEMAND_HANDLER_ID
from src.domain.ids import EventId, MachineId
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.domain.machine_sales import MachineSale
from src.infrastructure.outbox.memory import (
    OUTBOX_STATUS_FAILED,
    OUTBOX_STATUS_PENDING,
    InMemoryOutboxStore,
)
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.serialization import event_to_outbox_document
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.testing.settlement_fakes import InMemoryMachineSalesStore

_TZ = ZoneInfo("Europe/Moscow")
_SALES_DAY = date(2026, 10, 8)
_DAY_END = datetime(2026, 10, 9, 0, 0, tzinfo=_TZ)
_EVENT = DailySalesDemandRequested(
    event_id=EventId("daily_sales_demand:2026-10-08"),
    sales_day=_SALES_DAY,
    occurred_at=datetime(2026, 10, 9, 4, 0, tzinfo=UTC),
)
_RETRY_MINUTES = 15
_MAX_ATTEMPTS = 48
_PROJECT = UUID("33333333-3333-3333-3333-333333333333")
_SNACK_CH = UUID("11111111-1111-1111-1111-111111111111")


@dataclass(slots=True)
class _FakeRegistrar:
    calls: list[dict] = field(default_factory=list)
    permanent_fail: bool = False

    async def register_daily_sales_demand(self, **kwargs):  # type: ignore[no-untyped-def]
        if self.permanent_fail:
            raise RegistrarPermanentError("store missing")
        self.calls.append(kwargs)


def _handler_for_store(
    store: InMemoryMachineSalesStore,
    *,
    registrar: _FakeRegistrar | None = None,
    catalog: MappingSellableProductCodeCatalog | None = None,
) -> DailySalesDemandHandler:
    create = CreateDailySalesDemands(
        sales_store=store,
        registrar=registrar or _FakeRegistrar(),
        sellable_catalog=catalog or MappingSellableProductCodeCatalog(codes=frozenset({"P1"})),
        display_timezone="Europe/Moscow",
        project_id=_PROJECT,
        snack_sales_channel_id=_SNACK_CH,
    )
    return DailySalesDemandHandler(
        create_demands=create,
        not_ready_retry_minutes=_RETRY_MINUTES,
        not_ready_max_attempts=_MAX_ATTEMPTS,
    )


def test_demand_cursor_lag_stays_non_terminal() -> None:
    """happy: cursor lag → DeferredRetry → outbox entry stays alive (pending)."""
    asyncio.run(_test_demand_cursor_lag_stays_non_terminal())


async def _test_demand_cursor_lag_stays_non_terminal() -> None:
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(_DAY_END - timedelta(minutes=41))
    handler = _handler_for_store(store)
    outbox = InMemoryOutboxStore(max_attempts=5)
    processors = OutboxProcessorRegistry()
    processors.register(DAILY_SALES_DEMAND_HANDLER_ID, handler.process)
    outbox.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=DAILY_SALES_DEMAND_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )

    before = datetime.now(tz=UTC)
    worker = OutboxWorker(store=outbox, processors=processors)
    await worker.process_batch()

    entry = next(iter(outbox._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_PENDING
    assert entry["attempts"] == 1
    delta = entry["next_retry_at"] - before
    assert timedelta(minutes=14) <= delta <= timedelta(minutes=16)


def test_demand_caught_up_permanent_error_goes_terminal() -> None:
    """happy: cursor caught up → existing non-retryable rules may terminal."""
    asyncio.run(_test_demand_caught_up_permanent_error_goes_terminal())


async def _test_demand_caught_up_permanent_error_goes_terminal() -> None:
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(_DAY_END)
    store.insert_if_absent(
        MachineSale(
            source_id="s1",
            machine_id=MachineId("W1"),
            product_code="MISS",
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 10, 8, 12, 0, tzinfo=_TZ),
            ingested_at=datetime(2026, 10, 8, 12, 0, tzinfo=_TZ),
            sale_kind="snack",
            machine_code="W1",
            price=Decimal("10.00"),
        ),
    )
    handler = _handler_for_store(
        store,
        catalog=MappingSellableProductCodeCatalog(codes=frozenset({"OTHER"})),
    )
    outbox = InMemoryOutboxStore(max_attempts=5)
    processors = OutboxProcessorRegistry()
    processors.register(DAILY_SALES_DEMAND_HANDLER_ID, handler.process)
    outbox.enqueue(
        event_id=_EVENT.event_id.value,
        handler_id=DAILY_SALES_DEMAND_HANDLER_ID,
        event_document=event_to_outbox_document(_EVENT),
    )

    worker = OutboxWorker(store=outbox, processors=processors)
    await worker.process_batch()

    entry = next(iter(outbox._entries.values()))
    assert entry["status"] == OUTBOX_STATUS_FAILED
    assert "Sellable assortment missing codes" in entry["last_error"]


def test_handler_deferred_retry_on_cursor_lag() -> None:
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(_DAY_END - timedelta(seconds=1))
    handler = _handler_for_store(store)
    with pytest.raises(DeferredRetryOutboxError) as ei:
        asyncio.run(handler.process(_EVENT))
    assert ei.value.max_attempts == _MAX_ATTEMPTS
    assert isinstance(ei.value.__cause__, IngestCursorNotReady)


def test_unresolved_after_cursor_ready_is_non_retryable() -> None:
    store = InMemoryMachineSalesStore()
    store.save_global_cursor(_DAY_END)
    store.insert_if_absent(
        MachineSale(
            source_id="s1",
            machine_id=MachineId("W1"),
            product_code="MISS",
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 10, 8, 12, 0, tzinfo=_TZ),
            ingested_at=datetime(2026, 10, 8, 12, 0, tzinfo=_TZ),
            sale_kind="snack",
            machine_code="W1",
            price=Decimal("10.00"),
        ),
    )
    handler = _handler_for_store(
        store,
        catalog=MappingSellableProductCodeCatalog(codes=frozenset({"OTHER"})),
    )
    with pytest.raises(UnresolvedSellableCodesError) as ei:
        asyncio.run(handler.process(_EVENT))
    assert isinstance(ei.value, NonRetryableOutboxError)
