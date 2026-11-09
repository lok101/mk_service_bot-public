from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from tests.application.machine_pnl.fakes import (
    InMemoryLocationRentOccupancyPort,
    InMemoryMachineSalesWindowReader,
    InMemoryOpExParamsPort,
    InMemoryPeriodPnlStore,
    InMemoryPeriodSnapshotReader,
    InMemoryResidualSessionReader,
    InMemoryServiceFactCounter,
    InMemoryUnitCostCatalog,
    NoOpRentAccountantAlerter,
    NoOpZeroMaintenanceAlerter,
)

from src.application.form_submissions import NonRetryableOutboxError
from src.application.machine_pnl.errors import SnapshotNotFoundError
from src.application.machine_pnl.models import make_pnl_id
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.outbox.machine_pnl_period import MachinePnlPeriodHandler
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_pnl.events import MachinePeriodPnlRequested
from src.domain.machine_sales import MachineSale

_PERIOD_ID = "period-handler-1"
_SESSION_ID = "session-handler-1"
_MACHINE_ID = MachineId("101")
_TECH = TechnicianId("tech-1")
_SKU = "coffee-beans"
_OPENED = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_NOW = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)


def _snapshot() -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=_PERIOD_ID,
        machine_id=_MACHINE_ID,
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("rev-open"),
        closing_revision_id=RevisionId("rev-close"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(
            ReconciliationLine(
                product_code=_SKU,
                actual_prev=Decimal("10"),
                actual=Decimal("7"),
                calculated=Decimal("5"),
                delta=Decimal("2"),
                loads_total=Decimal("0"),
                sales_total=Decimal("3"),
            ),
        ),
        sales_lines=(),
        load_count=0,
        status="complete",
        reconciled=True,
    )


def _event() -> MachinePeriodPnlRequested:
    return MachinePeriodPnlRequested(
        event_id=EventId(f"machine_pnl:{_PERIOD_ID}"),
        period_id=_PERIOD_ID,
        source_session_id=_SESSION_ID,
        occurred_at=_NOW,
    )


def _handler(
    *,
    snapshots: InMemoryPeriodSnapshotReader | None = None,
    store: InMemoryPeriodPnlStore | None = None,
    load_unit_cost_catalog: Callable[[], InMemoryUnitCostCatalog] | None = None,
) -> tuple[MachinePnlPeriodHandler, InMemoryPeriodPnlStore]:
    snapshot_reader = snapshots if snapshots is not None else InMemoryPeriodSnapshotReader()
    pnl_store = store if store is not None else InMemoryPeriodPnlStore()
    sales = InMemoryMachineSalesWindowReader()
    sales.add(
        MachineSale(
            source_id="sale-1",
            machine_id=_MACHINE_ID,
            product_code=_SKU,
            quantity=Decimal("3"),
            occurred_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 5, 5, 11, 5, tzinfo=UTC),
            sale_kind="coffee",
            price=Decimal("50.00"),
        )
    )
    catalog = InMemoryUnitCostCatalog(_default=Decimal("10.00"))
    location_rent = InMemoryLocationRentOccupancyPort()
    location_rent.set(
        _MACHINE_ID,
        (
            LocationRentOccupancy(
                location_id="loc-a",
                machine_id=_MACHINE_ID,
                installed_at=_OPENED,
                removed_at=None,
                rent_monthly=Decimal("0"),
                rent_percent=None,
            ),
        ),
    )

    load_catalog = load_unit_cost_catalog or (lambda: catalog)

    handler = MachinePnlPeriodHandler(
        snapshots=snapshot_reader,
        sales=sales,
        period_pnl_store=pnl_store,
        load_unit_cost_catalog=load_catalog,
        residual_sessions=InMemoryResidualSessionReader(),
        load_opex_params=lambda: InMemoryOpExParamsPort.zeros(),
        service_facts=InMemoryServiceFactCounter(),
        zero_maintenance_alerter=NoOpZeroMaintenanceAlerter(),
        load_location_rent=lambda: location_rent,
        rent_accountant_alerter=NoOpRentAccountantAlerter(),
        rent_pending_retry_hours=24,
        rent_pending_max_attempts=7,
    )
    return handler, pnl_store


def test_machine_pnl_handler_happy_saves_period_pnl() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snapshot())
    handler, store = _handler(snapshots=snapshots)

    asyncio.run(handler.process(_event()))

    saved = store.get(make_pnl_id(_PERIOD_ID))
    assert saved is not None
    assert saved.period_id == _PERIOD_ID
    assert saved.revenue == Decimal("150.00")
    assert store.source_session_ids[make_pnl_id(_PERIOD_ID)] == _SESSION_ID


def test_machine_pnl_handler_missing_snapshot_fails() -> None:
    handler, store = _handler()
    with pytest.raises(SnapshotNotFoundError) as exc_info:
        asyncio.run(handler.process(_event()))
    assert not isinstance(exc_info.value, NonRetryableOutboxError)
    assert store.get(make_pnl_id(_PERIOD_ID)) is None


def test_machine_pnl_handler_reloads_global_and_rent_each_process() -> None:
    # happy: Callables invoked once per process
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snapshot())
    pnl_store = InMemoryPeriodPnlStore()
    sales = InMemoryMachineSalesWindowReader()
    sales.add(
        MachineSale(
            source_id="sale-1",
            machine_id=_MACHINE_ID,
            product_code=_SKU,
            quantity=Decimal("3"),
            occurred_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
            ingested_at=datetime(2026, 5, 5, 11, 5, tzinfo=UTC),
            sale_kind="coffee",
            price=Decimal("50.00"),
        )
    )
    catalog = InMemoryUnitCostCatalog(_default=Decimal("10.00"))
    opex_calls = {"n": 0}
    rent_calls = {"n": 0}

    def load_opex() -> InMemoryOpExParamsPort:
        opex_calls["n"] += 1
        return InMemoryOpExParamsPort.zeros()

    def load_rent() -> InMemoryLocationRentOccupancyPort:
        rent_calls["n"] += 1
        port = InMemoryLocationRentOccupancyPort()
        port.set(
            _MACHINE_ID,
            (
                LocationRentOccupancy(
                    location_id="loc-a",
                    machine_id=_MACHINE_ID,
                    installed_at=_OPENED,
                    removed_at=None,
                    rent_monthly=Decimal("0"),
                    rent_percent=None,
                ),
            ),
        )
        return port

    handler = MachinePnlPeriodHandler(
        snapshots=snapshots,
        sales=sales,
        period_pnl_store=pnl_store,
        load_unit_cost_catalog=lambda: catalog,
        residual_sessions=InMemoryResidualSessionReader(),
        load_opex_params=load_opex,
        service_facts=InMemoryServiceFactCounter(),
        zero_maintenance_alerter=NoOpZeroMaintenanceAlerter(),
        load_location_rent=load_rent,
        rent_accountant_alerter=NoOpRentAccountantAlerter(),
        rent_pending_retry_hours=24,
        rent_pending_max_attempts=7,
    )
    asyncio.run(handler.process(_event()))
    asyncio.run(handler.process(_event()))
    assert opex_calls["n"] == 2
    assert rent_calls["n"] == 2


def test_machine_pnl_handler_process_offloads_blocking_loader_to_thread() -> None:
    # edge: asyncio.to_thread не даёт блокирующему loader'у остановить event loop
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snapshot())

    def blocking_load_catalog() -> InMemoryUnitCostCatalog:
        time.sleep(0.2)
        return InMemoryUnitCostCatalog(_default=Decimal("10.00"))

    handler, _ = _handler(snapshots=snapshots, load_unit_cost_catalog=blocking_load_catalog)

    async def tick_counter() -> None:
        for _ in range(25):
            await asyncio.sleep(0.01)

    async def run_both() -> None:
        await asyncio.gather(handler.process(_event()), tick_counter())

    start = time.monotonic()
    asyncio.run(run_both())
    elapsed = time.monotonic() - start

    # concurrent (~0.40s measured) vs sequential (~0.60s measured) on this env.
    # Threshold raised from the original 0.35s design value to 0.5s: Windows asyncio
    # event loop timer granularity (~15.6ms, ProactorEventLoop) inflates tick_counter's
    # 25x asyncio.sleep(0.01) alone to ~0.39s, making 0.35s unreachable regardless of
    # to_thread offloading. 0.5s keeps a safety margin below the measured ~0.60s
    # sequential baseline while still proving concurrency (user-confirmed deviation).
    assert elapsed < 0.5
