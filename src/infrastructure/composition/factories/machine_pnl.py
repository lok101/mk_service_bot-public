from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, cast

from beartype import beartype
from pymongo import MongoClient

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.inventory_reconciliation.ports import (
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.machine_operations.ports import EventStore
from src.application.machine_pnl import FixtureOpExParamsCatalog
from src.application.machine_pnl.month_ports import MonthPnlSnapshotStore
from src.application.machine_pnl.opex_params import OpExParamsPort
from src.application.machine_pnl.ports import (
    PeriodPnlStore,
    UnitCostCatalog,
    as_period_snapshot_reader,
)
from src.application.machine_pnl.rent_ports import LocationRentOccupancyPort
from src.application.outbox.machine_pnl_month import MachinePnlMonthHandler
from src.application.outbox.machine_pnl_period import MachinePnlPeriodHandler
from src.application.product_identity.ports import DomainProductStore
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.config.settings import Settings
from src.infrastructure.composition.adapters.rent_accountant_alerter import (
    build_rent_accountant_alerter,
)
from src.infrastructure.composition.adapters.residual_session_reader import (
    SettlementResidualSessionReader,
)
from src.infrastructure.composition.adapters.service_fact_counter import (
    EventStoreServiceFactCounter,
)
from src.infrastructure.composition.adapters.zero_maintenance_alerter import (
    build_zero_maintenance_alerter,
)
from src.infrastructure.composition.factories.settlement import (
    build_machine_company_occupancy_store,
)
from src.infrastructure.machine_pnl.memory import InMemoryPeriodPnlStore
from src.infrastructure.machine_pnl.month_memory import InMemoryMonthPnlSnapshotStore
from src.infrastructure.machine_pnl.sheets_global_opex_catalog import (
    build_composed_opex_from_rows,
    load_global_opex_sheet_rows,
)
from src.infrastructure.machine_pnl.sheets_location_rent_catalog import (
    build_location_rent_catalog_from_rows,
    load_location_rent_sheet_rows,
)
from src.infrastructure.machine_pnl.sheets_unit_cost_catalog import (
    build_unit_cost_catalog_from_rows,
    load_unit_cost_sheet_rows,
)
from src.infrastructure.mongodb.machine_period_pnl import MongoPeriodPnlStore
from src.infrastructure.mongodb.machine_pnl_month_snapshot import MongoMonthPnlSnapshotStore


def _ttl_cached[T](loader: Callable[[], T], *, ttl_seconds: float) -> Callable[[], T]:
    state: dict[str, Any] = {"value": None, "expires_at": 0.0}

    def wrapped() -> T:
        now = time.monotonic()
        if state["value"] is None or now >= state["expires_at"]:
            state["value"] = loader()
            state["expires_at"] = now + ttl_seconds
        return cast(T, state["value"])

    return wrapped


@beartype
def build_period_pnl_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> PeriodPnlStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoPeriodPnlStore.from_settings(
            mongo,
            settings.machine_pnl,
            client=client,
        )
    return InMemoryPeriodPnlStore()


@beartype
def build_month_pnl_snapshot_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MonthPnlSnapshotStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMonthPnlSnapshotStore.from_settings(
            mongo,
            settings.machine_pnl_month,
            client=client,
        )
    return InMemoryMonthPnlSnapshotStore()


@beartype
def build_unit_cost_catalog_loader(settings: Settings) -> Callable[[], UnitCostCatalog]:
    pnl = settings.machine_pnl
    spreadsheet_id = pnl.unit_cost_spreadsheet_id
    sheet_id = pnl.unit_cost_sheet_id
    if spreadsheet_id is None or sheet_id is None:
        raise ValueError(
            "MACHINE_PNL_UNIT_COST_SPREADSHEET_ID and MACHINE_PNL_UNIT_COST_SHEET_ID "
            "are required when building unit cost catalog loader",
        )
    credentials_file = settings.google_sheets.credentials_file

    @beartype
    def load_catalog() -> UnitCostCatalog:
        rows = load_unit_cost_sheet_rows(
            credentials_file=credentials_file,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
        )
        return build_unit_cost_catalog_from_rows(rows)

    return _ttl_cached(load_catalog, ttl_seconds=pnl.catalog_cache_ttl_seconds)


@beartype
def build_opex_params_loader(settings: Settings) -> Callable[[], OpExParamsPort]:
    pnl = settings.machine_pnl
    spreadsheet_id = pnl.global_opex_spreadsheet_id
    sheet_id = pnl.global_opex_sheet_id
    if spreadsheet_id is None or sheet_id is None:
        raise ValueError("global opex sheet ids required when building opex params loader")
    credentials_file = settings.google_sheets.credentials_file

    @beartype
    def load() -> OpExParamsPort:
        rows = load_global_opex_sheet_rows(
            credentials_file=credentials_file,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
        )
        return build_composed_opex_from_rows(
            rows,
            machine=FixtureOpExParamsCatalog.default(),
        )

    return _ttl_cached(load, ttl_seconds=pnl.catalog_cache_ttl_seconds)


@beartype
def build_location_rent_loader(settings: Settings) -> Callable[[], LocationRentOccupancyPort]:
    pnl = settings.machine_pnl
    spreadsheet_id = pnl.location_rent_spreadsheet_id
    sheet_id = pnl.location_rent_sheet_id
    if spreadsheet_id is None or sheet_id is None:
        raise ValueError("location rent sheet ids required when building location rent loader")
    credentials_file = settings.google_sheets.credentials_file

    @beartype
    def load() -> LocationRentOccupancyPort:
        rows = load_location_rent_sheet_rows(
            credentials_file=credentials_file,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
        )
        return build_location_rent_catalog_from_rows(rows)

    return _ttl_cached(load, ttl_seconds=pnl.catalog_cache_ttl_seconds)


@beartype
def build_machine_pnl_period_handler(
    settings: Settings,
    *,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    machine_sales_store: MachineSalesStore | object,
    settlement_repository: TechnicianSettlementRepository,
    event_store: EventStore,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MachinePnlPeriodHandler | None:
    if not settings.machine_pnl.enabled:
        return None
    return MachinePnlPeriodHandler(
        snapshots=as_period_snapshot_reader(reconciliation_repo),
        sales=machine_sales_store,  # type: ignore[arg-type]
        period_pnl_store=build_period_pnl_store(settings, client=client),
        load_unit_cost_catalog=build_unit_cost_catalog_loader(settings),
        residual_sessions=SettlementResidualSessionReader(settlement_repository),
        load_opex_params=build_opex_params_loader(settings),
        service_facts=EventStoreServiceFactCounter(event_store),
        zero_maintenance_alerter=build_zero_maintenance_alerter(settings),
        load_location_rent=build_location_rent_loader(settings),
        rent_accountant_alerter=build_rent_accountant_alerter(settings),
        rent_pending_retry_hours=settings.machine_pnl.rent_pending_retry_hours,
        rent_pending_max_attempts=settings.machine_pnl.rent_pending_max_attempts,
        tax_enabled=settings.machine_pnl.tax_enabled,
    )


@beartype
def build_machine_pnl_month_handler(
    settings: Settings,
    *,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    machine_sales_store: MachineSalesStore | object,
    coffee_recipe_repo: CoffeeRecipeRepository,
    domain_product_store: DomainProductStore,
    event_store: EventStore,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MachinePnlMonthHandler | None:
    if not settings.machine_pnl_month.enabled:
        return None
    return MachinePnlMonthHandler(
        snapshots=as_period_snapshot_reader(reconciliation_repo),
        sales=machine_sales_store,  # type: ignore[arg-type]
        period_pnl_store=build_period_pnl_store(settings, client=client),
        month_store=build_month_pnl_snapshot_store(settings, client=client),
        recipes=coffee_recipe_repo,
        domain_products=domain_product_store,
        load_unit_cost_catalog=build_unit_cost_catalog_loader(settings),
        load_opex_params=build_opex_params_loader(settings),
        service_facts=EventStoreServiceFactCounter(event_store),
        load_location_rent=build_location_rent_loader(settings),
        company_occupancy=build_machine_company_occupancy_store(settings, client=client),
        ratio_lookback_periods=settings.machine_pnl_month.ratio_lookback_periods,
        tz=settings.service_calendar.zone_info(),
    )
