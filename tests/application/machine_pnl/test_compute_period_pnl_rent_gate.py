from __future__ import annotations

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
    NoOpZeroMaintenanceAlerter,
)

from src.application.machine_pnl import ComputePeriodPnl
from src.application.machine_pnl.errors import RentTermsPending
from src.application.machine_pnl.models import make_pnl_id
from src.application.machine_pnl.opex_params import OpExParamsPort
from src.application.machine_pnl.opex_ports import ServiceFactCounter, ZeroMaintenanceAlerter
from src.application.machine_pnl.rent_ports import LocationRentOccupancyPort
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.domain.ids import MachineId, RevisionId, TechnicianId
from src.domain.inventory_reconciliation.models import ReconciliationLine
from src.domain.inventory_reconciliation.snapshot import ResponsibilityPeriodReconciliation
from src.domain.machine_sales import MachineSale

_MACHINE_ID = MachineId("101")
_TECHNICIAN_ID = TechnicianId("tech-1")
_OPENED_AT = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
_CLOSED_AT = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
_PERIOD_ID = "period-rent-gate-1"
_SESSION_ID = "session-rent-gate-1"
_SKU = "coffee-beans"


def _snapshot() -> ResponsibilityPeriodReconciliation:
    return ResponsibilityPeriodReconciliation(
        period_id=_PERIOD_ID,
        machine_id=_MACHINE_ID,
        responsible_technician_id=_TECHNICIAN_ID,
        opening_revision_id=RevisionId("rev-open"),
        closing_revision_id=RevisionId("rev-close"),
        opened_at=_OPENED_AT,
        closed_at=_CLOSED_AT,
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


def _sale() -> MachineSale:
    return MachineSale(
        source_id="sale-1",
        machine_id=_MACHINE_ID,
        product_code=_SKU,
        quantity=Decimal("3"),
        occurred_at=datetime(2026, 5, 5, 11, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 5, 5, 11, 5, tzinfo=UTC),
        sale_kind="coffee",
        price=Decimal("50.00"),
    )


def _occupancy(
    *,
    rent_monthly: Decimal | None,
    rent_percent: Decimal | None = None,
) -> LocationRentOccupancy:
    return LocationRentOccupancy(
        location_id="loc-a",
        machine_id=_MACHINE_ID,
        installed_at=_OPENED_AT,
        removed_at=None,
        rent_monthly=rent_monthly,
        rent_percent=rent_percent,
    )


def _build_compute(
    *,
    rent_occupancies: tuple[LocationRentOccupancy, ...] | None = None,
    opex_params: OpExParamsPort | None = None,
    service_facts: ServiceFactCounter | None = None,
    zero_maintenance_alerter: ZeroMaintenanceAlerter | None = None,
    location_rent: LocationRentOccupancyPort | None = None,
    tax_enabled: bool = True,
) -> tuple[ComputePeriodPnl, InMemoryPeriodPnlStore]:
    snapshots = InMemoryPeriodSnapshotReader()
    snapshots.save(_snapshot())
    sales_reader = InMemoryMachineSalesWindowReader()
    sales_reader.add(_sale())
    store = InMemoryPeriodPnlStore()
    if opex_params is None:
        opex_params = InMemoryOpExParamsPort.zeros()
    if service_facts is None:
        facts = InMemoryServiceFactCounter()
        facts.set_default(1)
        service_facts = facts
    if zero_maintenance_alerter is None:
        zero_maintenance_alerter = NoOpZeroMaintenanceAlerter()
    if location_rent is None:
        port = InMemoryLocationRentOccupancyPort()
        if rent_occupancies is not None:
            port.set(_MACHINE_ID, rent_occupancies)
        location_rent = port
    use_case = ComputePeriodPnl(
        snapshots=snapshots,
        sales=sales_reader,
        unit_cost_catalog=InMemoryUnitCostCatalog(_default=Decimal("10.00")),
        period_pnl_store=store,
        residual_sessions=InMemoryResidualSessionReader(),
        opex_params=opex_params,
        service_facts=service_facts,
        zero_maintenance_alerter=zero_maintenance_alerter,
        location_rent=location_rent,
        tax_enabled=tax_enabled,
    )
    return use_case, store


def test_compute_period_pnl_empty_rent_no_persist() -> None:
    uc, store = _build_compute(rent_occupancies=(_occupancy(rent_monthly=None),))
    with pytest.raises(RentTermsPending) as ei:
        uc.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)
    assert ei.value.period_id == _PERIOD_ID
    assert ei.value.machine_id == _MACHINE_ID.value
    assert store.list_by_period_id(_PERIOD_ID) == ()
    assert store.get(make_pnl_id(_PERIOD_ID)) is None


def test_compute_period_pnl_explicit_zero_rent_persists() -> None:
    uc, store = _build_compute(rent_occupancies=(_occupancy(rent_monthly=Decimal("0")),))
    pnl = uc.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)
    assert store.get(pnl.pnl_id) is not None
    assert dict(pnl.opex_breakdown)["rent_fixed"] == Decimal("0.00")
    assert dict(pnl.opex_breakdown)["rent_percent"] == Decimal("0.00")


def test_compute_period_pnl_no_occupancy_no_persist() -> None:
    uc, store = _build_compute(rent_occupancies=())
    with pytest.raises(RentTermsPending):
        uc.execute(period_id=_PERIOD_ID, source_session_id=_SESSION_ID)
    assert store.list_by_period_id(_PERIOD_ID) == ()
    assert store.get(make_pnl_id(_PERIOD_ID)) is None
