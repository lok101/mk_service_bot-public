from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

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

from src.application.machine_pnl.models import make_pnl_id
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.machine_pnl.residual_ports import ResidualSessionView
from src.application.outbox.machine_pnl_period import MachinePnlPeriodHandler
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_pnl.events import MachinePeriodPnlRequested
from src.domain.machine_sales import MachineSale

_PERIOD_ID = "period-101"
_PERIOD_SIBLING = "period-102"
_SESSION_ID = "session-abc"
_MACHINE_ID = MachineId("101")
_TECH = TechnicianId("tech-1")
_SKU = "coffee-beans"
_OPENED = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_ANCHOR = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
_NOW = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)


def _zero_rent_port() -> InMemoryLocationRentOccupancyPort:
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


def _line(*, sales_total: Decimal) -> ReconciliationLine:
    return ReconciliationLine(
        product_code=_SKU,
        actual_prev=Decimal("10"),
        actual=Decimal("7"),
        calculated=Decimal("5"),
        delta=Decimal("2"),
        loads_total=Decimal("0"),
        sales_total=sales_total,
    )


def _snapshot(
    *,
    period_id: str,
    machine_id: MachineId,
    sales_total: Decimal,
) -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=period_id,
        machine_id=machine_id,
        responsible_technician_id=_TECH,
        opening_revision_id=RevisionId("rev-open"),
        closing_revision_id=RevisionId("rev-close"),
        opened_at=_OPENED,
        closed_at=_CLOSED,
        lines=(_line(sales_total=sales_total),),
        sales_lines=(),
        load_count=0,
        status="complete",
        reconciled=True,
    )


def test_machine_pnl_handler_passes_residual_reader() -> None:
    # residual -10 @ cost 2 → money_total=20; weights 3 and 1 → share current=15
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(
        _snapshot(period_id=_PERIOD_ID, machine_id=_MACHINE_ID, sales_total=Decimal("3")),
    )
    snapshots.save(
        _snapshot(
            period_id=_PERIOD_SIBLING,
            machine_id=MachineId("102"),
            sales_total=Decimal("1"),
        ),
    )
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
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_CLOSED.date(), cost=Decimal("10.00"))
    catalog.set(_SKU, as_of=_ANCHOR.date(), cost=Decimal("2.00"))
    store = InMemoryPeriodPnlStore()
    residual = InMemoryResidualSessionReader()
    residual.add(
        ResidualSessionView(
            session_id=_SESSION_ID,
            technician_id=_TECH.value,
            anchor_at=_ANCHOR,
            period_ids=(_PERIOD_ID, _PERIOD_SIBLING),
            residual_by_sku={_SKU: Decimal("-10")},
        )
    )
    handler = MachinePnlPeriodHandler(
        snapshots=snapshots,
        sales=sales,
        period_pnl_store=store,
        load_unit_cost_catalog=lambda: catalog,
        residual_sessions=residual,
        load_opex_params=lambda: InMemoryOpExParamsPort.zeros(),
        service_facts=InMemoryServiceFactCounter(),
        zero_maintenance_alerter=NoOpZeroMaintenanceAlerter(),
        load_location_rent=_zero_rent_port,
        rent_accountant_alerter=NoOpRentAccountantAlerter(),
        rent_pending_retry_hours=24,
        rent_pending_max_attempts=7,
    )

    asyncio.run(
        handler.process(
            MachinePeriodPnlRequested(
                event_id=EventId(f"machine_pnl:{_PERIOD_ID}"),
                period_id=_PERIOD_ID,
                source_session_id=_SESSION_ID,
                occurred_at=_NOW,
            )
        )
    )

    saved = store.get(make_pnl_id(_PERIOD_ID))
    assert saved is not None
    assert saved.allocated_shortage == Decimal("15.00")
    assert residual.calls == [(_PERIOD_ID, _TECH.value)]
