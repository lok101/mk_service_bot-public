from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from tests.application.machine_pnl.fakes import (
    InMemoryLocationRentOccupancyPort,
    InMemoryMachineSalesWindowReader,
    InMemoryOpExParamsPort,
    InMemoryPeriodPnlStore,
    InMemoryPeriodSnapshotReader,
    InMemoryServiceFactCounter,
    InMemoryUnitCostCatalog,
)

from src.application.form_submissions import NonRetryableOutboxError
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.outbox.machine_pnl_month import MachinePnlMonthHandler
from src.domain.ids import EventId, MachineId
from src.domain.machine_pnl.events import MachineMonthPnlRequested, MachinePeriodPnlRequested
from src.infrastructure.machine_pnl.month_memory import InMemoryMonthPnlSnapshotStore
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)

_MACHINE_ID = MachineId("101")
_PERIOD_ID = "period-handler-1"
_SESSION_ID = "session-handler-1"
_NOW = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
_TZ = ZoneInfo("UTC")


def _month_event() -> MachineMonthPnlRequested:
    return MachineMonthPnlRequested(
        event_id=EventId("machine_pnl_month:p1"),
        machine_id="101",
        period_start_dates=(date(2026, 6, 1),),
        source_period_id="p1",
        occurred_at=_NOW,
    )


def _period_event() -> MachinePeriodPnlRequested:
    return MachinePeriodPnlRequested(
        event_id=EventId(f"machine_pnl:{_PERIOD_ID}"),
        period_id=_PERIOD_ID,
        source_session_id=_SESSION_ID,
        occurred_at=_NOW,
    )


def _month_handler(
    *,
    month_store: InMemoryMonthPnlSnapshotStore,
) -> MachinePnlMonthHandler:
    catalog = InMemoryUnitCostCatalog()
    location_rent = InMemoryLocationRentOccupancyPort()
    location_rent.set(
        _MACHINE_ID,
        (
            LocationRentOccupancy(
                location_id="loc-a",
                machine_id=_MACHINE_ID,
                installed_at=datetime(2026, 1, 1, tzinfo=UTC),
                removed_at=None,
                rent_monthly=Decimal("0"),
                rent_percent=None,
            ),
        ),
    )
    return MachinePnlMonthHandler(
        snapshots=InMemoryPeriodSnapshotReader(),
        sales=InMemoryMachineSalesWindowReader(),
        period_pnl_store=InMemoryPeriodPnlStore(),
        month_store=month_store,
        recipes=InMemoryCoffeeRecipeRepository(),
        domain_products=__import__(
            "tests.application.product_identity.fakes",
            fromlist=["FakeDomainProductStore"],
        ).FakeDomainProductStore(),
        load_unit_cost_catalog=lambda: catalog,
        load_opex_params=lambda: InMemoryOpExParamsPort.zeros(),
        service_facts=InMemoryServiceFactCounter(),
        load_location_rent=lambda: location_rent,
        company_occupancy=InMemoryMachineCompanyOccupancyStore(),
        ratio_lookback_periods=3,
        tz=_TZ,
    )


def test_handler_upserts_affected_months_without_sheets() -> None:
    month_store = InMemoryMonthPnlSnapshotStore()
    handler = _month_handler(month_store=month_store)
    asyncio.run(handler.process(_month_event()))
    assert month_store.get(MachineId("101"), date(2026, 6, 1)) is not None
    assert not hasattr(handler, "sheet_writer")


def test_handler_rejects_unsupported_event() -> None:
    handler = _month_handler(month_store=InMemoryMonthPnlSnapshotStore())
    with pytest.raises(NonRetryableOutboxError):
        asyncio.run(handler.process(_period_event()))
