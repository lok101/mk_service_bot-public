from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from tests.application.machine_pnl.fakes import (
    InMemoryLocationRentOccupancyPort,
    InMemoryMachineSalesWindowReader,
    InMemoryOpExParamsPort,
    InMemoryPeriodPnlStore,
    InMemoryPeriodSnapshotReader,
    InMemoryServiceFactCounter,
    InMemoryUnitCostCatalog,
)
from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)

from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.outbox.handler_ids import MACHINE_PNL_MONTH_HANDLER_ID
from src.application.outbox.machine_pnl_month import MachinePnlMonthHandler
from src.domain.ids import MachineId
from src.domain.machine_pnl.events import MachineMonthPnlRequested
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.machine_pnl.month_memory import InMemoryMonthPnlSnapshotStore
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.company_occupancy_fakes import (
    InMemoryMachineCompanyOccupancyStore,
)


def _stub_month_handler() -> MachinePnlMonthHandler:
    catalog = InMemoryUnitCostCatalog()
    machine_id = MachineId("101")
    location_rent = InMemoryLocationRentOccupancyPort()
    opened = datetime(2026, 5, 1, tzinfo=UTC)
    location_rent.set(
        machine_id,
        (
            LocationRentOccupancy(
                location_id="loc-a",
                machine_id=machine_id,
                installed_at=opened,
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
        month_store=InMemoryMonthPnlSnapshotStore(),
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
        tz=ZoneInfo("UTC"),
    )


def test_month_handler_absent_when_disabled() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        machine_pnl_month_handler=None,
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
    )

    assert processors.is_registered(MACHINE_PNL_MONTH_HANDLER_ID) is False
    assert MACHINE_PNL_MONTH_HANDLER_ID not in publisher.handler_ids_for(
        MachineMonthPnlRequested,
    )


def test_month_handler_registered_when_enabled() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        machine_pnl_month_handler=_stub_month_handler(),
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )

    assert processors.is_registered(MACHINE_PNL_MONTH_HANDLER_ID)
    assert MACHINE_PNL_MONTH_HANDLER_ID in publisher.handler_ids_for(
        MachineMonthPnlRequested,
    )
