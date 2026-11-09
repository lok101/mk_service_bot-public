from __future__ import annotations

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
    NoOpZeroMaintenanceAlerter,
)

from src.application.machine_pnl import ComputePeriodPnl
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale

_MACHINE_ID = MachineId("101")
_TECH = TechnicianId("tech-1")
_OPENED = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_SKU = "coffee-beans"


def _occupancy() -> LocationRentOccupancy:
    return LocationRentOccupancy(
        location_id="loc-test",
        machine_id=_MACHINE_ID,
        installed_at=_OPENED,
        removed_at=None,
        rent_monthly=Decimal("0"),
        rent_percent=None,
    )


def _snapshot() -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id="period-101",
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
        reconciled=False,
    )


def _use_case() -> tuple[ComputePeriodPnl, InMemoryPeriodPnlStore]:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snapshot())
    sales = InMemoryMachineSalesWindowReader()
    sales.add(
        MachineSale(
            source_id="s1",
            machine_id=_MACHINE_ID,
            product_code=_SKU,
            quantity=Decimal("1"),
            occurred_at=datetime(2026, 5, 2, tzinfo=UTC),
            ingested_at=datetime(2026, 5, 2, tzinfo=UTC),
            sale_kind="coffee",
            price=Decimal("10"),
        )
    )
    catalog = InMemoryUnitCostCatalog()
    catalog.set(_SKU, as_of=_CLOSED.date(), cost=Decimal("1"))
    store = InMemoryPeriodPnlStore()
    rent = InMemoryLocationRentOccupancyPort()
    rent.set(_MACHINE_ID, (_occupancy(),))
    use_case = ComputePeriodPnl(
        snapshots=snapshots,
        sales=sales,
        unit_cost_catalog=catalog,
        period_pnl_store=store,
        residual_sessions=InMemoryResidualSessionReader(),
        opex_params=InMemoryOpExParamsPort.zeros(),
        service_facts=InMemoryServiceFactCounter(),
        zero_maintenance_alerter=NoOpZeroMaintenanceAlerter(),
        location_rent=rent,
        tax_enabled=False,
    )
    return use_case, store


def test_compute_period_pnl_sets_location_id_from_occupancy() -> None:
    use_case, store = _use_case()
    pnl = use_case.execute(period_id="period-101", source_session_id="sess")
    assert pnl.location_id == "loc-test"
    loaded = store.get(pnl.pnl_id)
    assert loaded is not None
    assert loaded.location_id == "loc-test"


def test_compute_period_pnl_sets_technician_id_from_snapshot() -> None:
    use_case, _store = _use_case()
    pnl = use_case.execute(period_id="period-101", source_session_id="sess")
    assert pnl.technician_id == "tech-1"
