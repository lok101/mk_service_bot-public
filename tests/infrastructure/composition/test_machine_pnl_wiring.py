from __future__ import annotations

from dataclasses import replace

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
from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)

from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.outbox.handler_ids import MACHINE_PNL_PERIOD_HANDLER_ID
from src.application.outbox.machine_pnl_period import MachinePnlPeriodHandler
from src.domain.ids import MachineId
from src.domain.machine_pnl.events import MachinePeriodPnlRequested
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher


def _stub_handler() -> MachinePnlPeriodHandler:
    catalog = InMemoryUnitCostCatalog()
    machine_id = MachineId("101")
    location_rent = InMemoryLocationRentOccupancyPort()
    from datetime import UTC, datetime
    from decimal import Decimal

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
    return MachinePnlPeriodHandler(
        snapshots=InMemoryPeriodSnapshotReader(),
        sales=InMemoryMachineSalesWindowReader(),
        period_pnl_store=InMemoryPeriodPnlStore(),
        load_unit_cost_catalog=lambda: catalog,
        residual_sessions=InMemoryResidualSessionReader(),
        load_opex_params=lambda: InMemoryOpExParamsPort.zeros(),
        service_facts=InMemoryServiceFactCounter(),
        zero_maintenance_alerter=NoOpZeroMaintenanceAlerter(),
        load_location_rent=lambda: location_rent,
        rent_accountant_alerter=NoOpRentAccountantAlerter(),
        rent_pending_retry_hours=24,
        rent_pending_max_attempts=7,
    )


def test_machine_pnl_handler_not_registered_when_disabled() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        machine_pnl_period_handler=None,
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
    )

    assert processors.is_registered(MACHINE_PNL_PERIOD_HANDLER_ID) is False
    assert MACHINE_PNL_PERIOD_HANDLER_ID not in publisher.handler_ids_for(
        MachinePeriodPnlRequested,
    )


def test_machine_pnl_handler_registered_when_enabled() -> None:
    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        machine_pnl_period_handler=_stub_handler(),
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
        process="effects",
    )

    assert processors.is_registered(MACHINE_PNL_PERIOD_HANDLER_ID)
    assert MACHINE_PNL_PERIOD_HANDLER_ID in publisher.handler_ids_for(
        MachinePeriodPnlRequested,
    )
