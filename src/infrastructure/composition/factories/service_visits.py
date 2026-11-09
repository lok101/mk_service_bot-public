from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from beartype import beartype
from pymongo import MongoClient

from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.machine_operations.ports import EventStore
from src.application.service_visits.memory import InMemoryServiceVisitStore
from src.application.service_visits.ports import (
    MachineSalesQtyBaselineLookup,
    MaintenanceOnOperationalDayLookup,
    ServiceVisitStore,
)
from src.config.settings import Settings
from src.infrastructure.composition.adapters import (
    EventStoreMaintenanceOnOperationalDayLookup,
    MachineSalesStoreQtyBaselineLookup,
)
from src.infrastructure.mongodb.service_visits import MongoServiceVisitStore


@beartype
def build_service_visit_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> ServiceVisitStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoServiceVisitStore.from_settings(
            mongo,
            settings.service_visits,
            client=client,
        )
    return InMemoryServiceVisitStore()


@beartype
def build_maintenance_on_operational_day_lookup(
    event_store: EventStore,
) -> MaintenanceOnOperationalDayLookup:
    return EventStoreMaintenanceOnOperationalDayLookup(event_store=event_store)


@beartype
def build_machine_sales_qty_baseline_lookup(
    *,
    sales: MachineSalesStore,
    timezone: ZoneInfo,
    days_for_average: int,
    baseline_min_points: int,
    baseline_winsorize_min_points: int,
    baseline_winsorize_percent: int,
) -> MachineSalesQtyBaselineLookup:
    return MachineSalesStoreQtyBaselineLookup(
        sales=sales,
        timezone=timezone,
        days_for_average=days_for_average,
        baseline_min_points=baseline_min_points,
        baseline_winsorize_min_points=baseline_winsorize_min_points,
        baseline_winsorize_percent=baseline_winsorize_percent,
    )
