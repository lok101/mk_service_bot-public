from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from beartype import beartype
from google.oauth2 import service_account
from googleapiclient.discovery import build

from src.application.machine_pnl import ComputeMonthPnlSnapshot
from src.application.machine_pnl.ports import as_period_snapshot_reader
from src.application.master_data.company_directory import KitCompanyDirectory
from src.application.reference_data import ReferenceDataProvider
from src.config.settings import Settings
from src.domain.ids import TechnicianId
from src.infrastructure.composition.adapters.service_fact_counter import (
    EventStoreServiceFactCounter,
)
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.factories import (
    attach_master_data,
    attach_technicians,
    build_coffee_recipe_repository,
    build_company_store,
    build_event_store,
    build_machine_company_occupancy_store,
    build_machine_sales_store,
    build_master_data_stores,
    build_period_reconciliation_repository,
    build_reference_data_snapshot_store,
    build_reference_data_sync,
    build_technician_store,
    build_vending_machine_repository,
    warm_up_reference_data_provider,
)
from src.infrastructure.composition.factories.company_directory import (
    build_kit_company_directory,
)
from src.infrastructure.composition.factories.machine_pnl import (
    build_location_rent_loader,
    build_month_pnl_snapshot_store,
    build_opex_params_loader,
    build_period_pnl_store,
    build_unit_cost_catalog_loader,
)
from src.infrastructure.composition.factories.product_identity import (
    build_domain_product_store,
)
from src.infrastructure.composition.machine_pnl_month_worker_container import (
    MachinePnlMonthWorkerContainer,
)
from src.infrastructure.integrations.google.sheets.sheet_reader import (
    GOOGLE_SHEETS_WRITE_SCOPE,
)
from src.infrastructure.machine_pnl.month_sheet_export_writer import MonthPnlSheetExportWriter
from src.infrastructure.machine_pnl_month_worker.cron_scheduler import (
    MachinePnlMonthCronScheduler,
)
from src.infrastructure.machine_pnl_month_worker.cron_tick import run_machine_pnl_month_tick
from src.infrastructure.machine_pnl_month_worker.mongo_worker_status import (
    MongoMachinePnlMonthWorkerStatusRepository,
)
from src.infrastructure.machine_pnl_month_worker.worker_runtime import (
    MachinePnlMonthWorkerRuntime,
)


@beartype
class _SystemUtcClock:
    def now_utc_iso(self) -> str:
        return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@beartype
class _InMemoryWorkerStatusRepository:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, bool]] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.heartbeats.append((at, enabled))


def _location_display_lookup(
    provider: ReferenceDataProvider,
) -> Callable[[str], str]:
    def lookup(location_id: str) -> str:
        directory = provider.locations_directory_or_none()
        if directory is None:
            return ""
        placement = directory.by_location_id.get(location_id)
        if placement is None:
            return ""
        return placement.name

    return lookup


def _technician_name_lookup(provider: ReferenceDataProvider) -> Callable[[str], str]:
    def lookup(technician_id: str) -> str:
        if not technician_id.strip():
            return ""
        directory = provider.technicians_directory_or_none()
        if directory is None:
            return ""
        return directory.names_by_id.get(TechnicianId(technician_id), "")

    return lookup


def _company_name_lookup(directory: KitCompanyDirectory) -> Callable[[int], str]:
    def lookup(company_id: int) -> str:
        return directory.display_name(company_id)

    return lookup


def _build_month_sheet_writer(
    settings: Settings,
    *,
    timezone: ZoneInfo,
    provider: ReferenceDataProvider,
    company_directory: KitCompanyDirectory,
) -> MonthPnlSheetExportWriter:
    spreadsheet_id = settings.machine_pnl_month.sheet_spreadsheet_id
    sheet_id = settings.machine_pnl_month.sheet_id
    assert spreadsheet_id is not None
    assert sheet_id is not None
    credentials_file = settings.google_sheets.credentials_file.strip()

    def _service() -> Any:
        credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            credentials_file,
            scopes=[GOOGLE_SHEETS_WRITE_SCOPE],
        )
        return build("sheets", "v4", credentials=credentials)

    return MonthPnlSheetExportWriter(
        service_factory=_service,
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_id,
        tz=timezone,
        location_display_lookup=_location_display_lookup(provider),
        technician_name_lookup=_technician_name_lookup(provider),
        company_name_lookup=_company_name_lookup(company_directory),
    )


@beartype
def wire_machine_pnl_month_worker(
    settings: Settings,
    *,
    persistence: PersistenceBundle,
) -> MachinePnlMonthWorkerContainer:
    enabled = settings.machine_pnl_month.worker_enabled
    mongo_client = persistence.mongo_client
    timezone: ZoneInfo = settings.service_calendar.zone_info()

    if enabled and (mongo_client is None or not settings.mongodb.is_configured):
        raise ValueError(
            "MACHINE_PNL_MONTH_WORKER_ENABLED=true requires a configured MongoDB client",
        )

    if mongo_client is not None and settings.mongodb.is_configured:
        status_repository: (
            MongoMachinePnlMonthWorkerStatusRepository | _InMemoryWorkerStatusRepository
        ) = MongoMachinePnlMonthWorkerStatusRepository.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
    else:
        status_repository = _InMemoryWorkerStatusRepository()

    extra_closers: tuple[Callable[[], None], ...] = ()

    if enabled:
        assert mongo_client is not None
        reference_store = build_reference_data_snapshot_store(settings, client=mongo_client)
        provider = ReferenceDataProvider()
        reference_sync = build_reference_data_sync(
            settings,
            store=reference_store,
            provider=provider,
        )
        warm_up_reference_data_provider(
            provider=provider,
            store=reference_store,
            sync=reference_sync,
        )
        master_data_stores = build_master_data_stores(settings, mongo_client=mongo_client)
        attach_master_data(
            provider,
            stores=master_data_stores,
            enabled=settings.master_data.enabled,
        )
        technician_store = build_technician_store(settings, mongo_client=mongo_client)
        attach_technicians(
            provider,
            store=technician_store,
            enabled=settings.master_data.technicians_enabled,
        )
        machines_repo = build_vending_machine_repository(provider)
        event_store = build_event_store(settings, client=mongo_client)
        reconciliation_repo = build_period_reconciliation_repository(
            settings,
            client=mongo_client,
        )
        sales = build_machine_sales_store(settings, client=mongo_client)
        recipes = build_coffee_recipe_repository(settings, client=mongo_client)
        domain_products = build_domain_product_store(
            settings.mongodb,
            settings.domain_product_identity,
            client=mongo_client,
        )
        period_pnl_store = build_period_pnl_store(settings, client=mongo_client)
        month_store = build_month_pnl_snapshot_store(settings, client=mongo_client)
        company_occupancy = build_machine_company_occupancy_store(
            settings,
            client=mongo_client,
        )
        load_unit_cost_catalog = build_unit_cost_catalog_loader(settings)
        load_opex_params = build_opex_params_loader(settings)
        load_location_rent = build_location_rent_loader(settings)
        service_facts = EventStoreServiceFactCounter(event_store)
        company_store = build_company_store(settings, mongo_client=mongo_client)
        company_directory = build_kit_company_directory(company_store)
        sheet_writer = _build_month_sheet_writer(
            settings,
            timezone=timezone,
            provider=provider,
            company_directory=company_directory,
        )
        ratio_lookback = settings.machine_pnl_month.ratio_lookback_periods

        def cron_callback() -> None:
            warm_up_reference_data_provider(
                provider=provider,
                store=reference_store,
                sync=reference_sync,
            )
            attach_master_data(
                provider,
                stores=master_data_stores,
                enabled=settings.master_data.enabled,
            )
            attach_technicians(
                provider,
                store=technician_store,
                enabled=settings.master_data.technicians_enabled,
            )
            catalog = load_unit_cost_catalog()
            opex_params = load_opex_params()
            location_rent = load_location_rent()
            compute = ComputeMonthPnlSnapshot(
                sales=sales,
                unit_cost_catalog=catalog,
                recipes=recipes,
                domain_products=domain_products,
                period_pnl_store=period_pnl_store,
                snapshots=as_period_snapshot_reader(reconciliation_repo),
                opex_params=opex_params,
                service_facts=service_facts,
                location_rent=location_rent,
                company_occupancy=company_occupancy,
                month_store=month_store,
                ratio_lookback_periods=ratio_lookback,
                tz=timezone,
            )
            now = datetime.now(timezone)
            run_machine_pnl_month_tick(
                machines=machines_repo.list_all(),
                compute=compute,
                sheet_writer=sheet_writer,
                today=now.date(),
                tz=timezone,
                month_store=month_store,
            )

        callback = cron_callback
    else:

        def callback() -> None:
            return None

    scheduler = MachinePnlMonthCronScheduler(
        enabled=enabled,
        interval_hours=settings.machine_pnl_month.worker_interval_hours,
        timezone=timezone,
        callback=callback,
    )
    runtime = MachinePnlMonthWorkerRuntime(
        enabled=enabled,
        status_repository=status_repository,
        scheduler=scheduler,
        clock=_SystemUtcClock(),
    )
    return MachinePnlMonthWorkerContainer(
        runtime=runtime,
        persistence=persistence,
        extra_closers=extra_closers,
    )


# Re-export for tests that monkeypatch wire module symbols.
__all__ = (
    "_InMemoryWorkerStatusRepository",
    "_SystemUtcClock",
    "_company_name_lookup",
    "wire_machine_pnl_month_worker",
)
