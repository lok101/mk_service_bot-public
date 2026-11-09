from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)

from src.application.outbox.daily_sales_demand import DailySalesDemandHandler
from src.application.outbox.handler_ids import DAILY_SALES_DEMAND_HANDLER_ID
from src.config.daily_sales_demand import DailySalesDemandSettings
from src.domain.inventory_reconciliation.events import DailySalesDemandRequested
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher


@dataclass(slots=True)
class _StubCreateDemands:
    async def execute(self, *, sales_day: date) -> None:
        return None


def _stub_handler() -> DailySalesDemandHandler:
    return DailySalesDemandHandler(
        create_demands=_StubCreateDemands(),
        not_ready_retry_minutes=15,
        not_ready_max_attempts=48,
    )


def test_daily_sales_demand_on_effects_off_ingress() -> None:
    """happy: processor on effects (ADR-0083); no subscribe here (worker enqueues)."""
    assert DailySalesDemandSettings(worker_enabled=True).worker_enabled is True
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        daily_sales_demand_handler=_stub_handler(),
    )

    ingress_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    ingress_processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=ingress_publisher,
        processors=ingress_processors,
        deps=deps,
        process="ingress",
    )
    assert ingress_processors.is_registered(DAILY_SALES_DEMAND_HANDLER_ID) is False
    assert DAILY_SALES_DEMAND_HANDLER_ID not in ingress_publisher.handler_ids_for(
        DailySalesDemandRequested,
    )

    effects_publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    effects_processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=effects_publisher,
        processors=effects_processors,
        deps=deps,
        process="effects",
    )
    assert effects_processors.is_registered(DAILY_SALES_DEMAND_HANDLER_ID) is True
    assert DAILY_SALES_DEMAND_HANDLER_ID not in effects_publisher.handler_ids_for(
        DailySalesDemandRequested,
    )


def test_skips_daily_sales_demand_when_disabled() -> None:
    assert DailySalesDemandSettings(worker_enabled=False).worker_enabled is False

    store = InMemoryOutboxStore()
    publisher = OutboxDomainEventPublisher(store=store)
    processors = OutboxProcessorRegistry()
    deps = replace(
        _minimal_outbox_handler_deps(include_post_accountability=False),
        daily_sales_demand_handler=None,
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=deps,
    )

    assert processors.is_registered(DAILY_SALES_DEMAND_HANDLER_ID) is False
    assert DAILY_SALES_DEMAND_HANDLER_ID not in publisher.handler_ids_for(
        DailySalesDemandRequested,
    )
