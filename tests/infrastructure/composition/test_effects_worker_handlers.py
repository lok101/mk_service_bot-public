from __future__ import annotations

from dataclasses import replace
from datetime import date

from tests.infrastructure.composition.test_register_outbox_handlers import (
    _minimal_outbox_handler_deps,
)

from src.application.outbox.daily_sales_demand import DailySalesDemandHandler
from src.application.outbox.handler_ids import (
    DAILY_SALES_DEMAND_HANDLER_ID,
    LOADING_PHOTOS_HANDLER_ID,
    LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
    LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
    NO_SALES_INCIDENT_CONTROL_HANDLER_ID,
    PERIOD_RECONCILIATION_HANDLER_ID,
    SERVICE_VISIT_INCIDENT_HANDLER_ID,
    SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
    TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
)
from src.application.visit_photo_grouping import VISIT_PHOTO_GROUPING_HANDLER_ID
from src.domain.machine_operations.events import PhotosSubmitted
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    register_outbox_handlers,
)
from src.infrastructure.outbox import InMemoryOutboxStore
from src.infrastructure.outbox.processor import OutboxProcessorRegistry
from src.infrastructure.outbox.publisher import OutboxDomainEventPublisher
from src.infrastructure.sales_monitoring.memory_audit import InMemorySalesMonitoringAuditStore

_MOVED_CORE = frozenset(
    {
        TECHNICIAN_WAREHOUSE_LOADING_HANDLER_ID,
        LOADING_PHOTOS_HANDLER_ID,
        LOADING_PHOTOS_INTEGRITY_HANDLER_ID,
        LOADING_PHOTOS_TELEGRAM_HANDLER_ID,
        PERIOD_RECONCILIATION_HANDLER_ID,
        SERVICE_VISIT_ON_MAINTENANCE_HANDLER_ID,
        DAILY_SALES_DEMAND_HANDLER_ID,
    }
)


class _Demands:
    async def execute(self, *, sales_day: date) -> None:
        del sales_day


def _deps():
    return replace(
        _minimal_outbox_handler_deps(include_post_accountability=True),
        sales_monitoring_audit_store=InMemorySalesMonitoringAuditStore(),
        daily_sales_demand_handler=DailySalesDemandHandler(
            create_demands=_Demands(),
            not_ready_retry_minutes=1,
            not_ready_max_attempts=1,
        ),
        visit_photo_grouping_enabled=True,
    )


def _register(process: str) -> tuple[OutboxProcessorRegistry, OutboxDomainEventPublisher]:
    publisher = OutboxDomainEventPublisher(store=InMemoryOutboxStore())
    processors = OutboxProcessorRegistry()
    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        deps=_deps(),
        process=process,
    )
    return processors, publisher


def test_effects_and_app_handler_sets_are_disjoint() -> None:
    ingress, _ingress_publisher = _register("ingress")
    effects, _effects_publisher = _register("effects")
    ingress_ids = ingress.registered_handler_ids()
    effects_ids = effects.registered_handler_ids()

    assert ingress_ids.isdisjoint(effects_ids)
    assert effects_ids == _MOVED_CORE
    assert ingress_ids == frozenset({NO_SALES_INCIDENT_CONTROL_HANDLER_ID})


def test_app_does_not_register_foreign_backup_handlers() -> None:
    ingress, ingress_publisher = _register("ingress")
    effects, effects_publisher = _register("effects")

    assert DAILY_SALES_DEMAND_HANDLER_ID not in ingress.registered_handler_ids()
    assert DAILY_SALES_DEMAND_HANDLER_ID in effects.registered_handler_ids()
    assert SERVICE_VISIT_INCIDENT_HANDLER_ID not in ingress.registered_handler_ids()
    assert SERVICE_VISIT_INCIDENT_HANDLER_ID not in effects.registered_handler_ids()
    assert VISIT_PHOTO_GROUPING_HANDLER_ID not in ingress.registered_handler_ids()
    assert VISIT_PHOTO_GROUPING_HANDLER_ID not in effects.registered_handler_ids()
    assert VISIT_PHOTO_GROUPING_HANDLER_ID in ingress_publisher.handler_ids_for(PhotosSubmitted)
    assert VISIT_PHOTO_GROUPING_HANDLER_ID not in effects_publisher.handler_ids_for(PhotosSubmitted)


def test_same_handler_id_is_not_in_both_processes() -> None:
    ingress, _ = _register("ingress")
    effects, _ = _register("effects")
    overlap = ingress.registered_handler_ids() & effects.registered_handler_ids()
    assert overlap == frozenset()
