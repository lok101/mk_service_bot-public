from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal

from tests.application.machine_pnl.fakes import (
    InMemoryLocationRentOccupancyPort,
    InMemoryMachineSalesWindowReader,
    InMemoryPeriodPnlStore,
    InMemoryPeriodSnapshotReader,
    InMemoryResidualSessionReader,
    InMemoryServiceFactCounter,
    InMemoryUnitCostCatalog,
    NoOpRentAccountantAlerter,
    NoOpZeroMaintenanceAlerter,
)

from src.application.machine_pnl.models import make_pnl_id
from src.application.machine_pnl.opex_params import (
    FixtureMachineOpExRow,
    FixtureOpExParamsCatalog,
    FixtureRateRow,
)
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.outbox.machine_pnl_period import MachinePnlPeriodHandler
from src.domain.ids import EventId, MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_pnl.events import MachinePeriodPnlRequested
from src.domain.machine_sales import MachineSale

_PERIOD_ID = "period-opex-wire-1"
_SESSION_ID = "session-opex-wire-1"
_MACHINE_ID = MachineId("101")
_TECH = TechnicianId("tech-1")
_SKU = "coffee-beans"
_OPENED = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_NOW = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)


def test_machine_pnl_handler_passes_opex_deps() -> None:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(
        ResponsibilityPeriodReconciliation(
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
    catalog = InMemoryUnitCostCatalog(_default=Decimal("10.00"))
    store = InMemoryPeriodPnlStore()
    counter = InMemoryServiceFactCounter()
    counter.set_default(2)
    opex_params = FixtureOpExParamsCatalog(
        machine_rows=(
            FixtureMachineOpExRow(
                machine_id=_MACHINE_ID,
                valid_from=date(2026, 1, 1),
                rent_monthly=Decimal("310.00"),
                rent_percent=Decimal("0"),
                duty_mode="patent",
                patent_monthly=Decimal("0"),
                tax_percent=Decimal("0"),
                acquiring_percent=Decimal("0"),
                acquiring_fee_per_sale=Decimal("0"),
                terminal_monthly=Decimal("0"),
            ),
        ),
        labor_global_rows=(FixtureRateRow(valid_from=date(2026, 1, 1), amount=Decimal("100.00")),),
    )
    location_rent = InMemoryLocationRentOccupancyPort()
    location_rent.set(
        _MACHINE_ID,
        (
            LocationRentOccupancy(
                location_id="loc-a",
                machine_id=_MACHINE_ID,
                installed_at=_OPENED,
                removed_at=None,
                rent_monthly=Decimal("310.00"),
                rent_percent=Decimal("0"),
            ),
        ),
    )
    handler = MachinePnlPeriodHandler(
        snapshots=snapshots,
        sales=sales,
        period_pnl_store=store,
        load_unit_cost_catalog=lambda: catalog,
        residual_sessions=InMemoryResidualSessionReader(),
        load_opex_params=lambda: opex_params,
        service_facts=counter,
        zero_maintenance_alerter=NoOpZeroMaintenanceAlerter(),
        load_location_rent=lambda: location_rent,
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
    assert saved.opex > Decimal("0")
    assert dict(saved.opex_breakdown)["labor"] == Decimal("200.00")
    assert dict(saved.opex_breakdown)["rent_fixed"] == Decimal("90.00")
