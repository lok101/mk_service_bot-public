from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from beartype import beartype
from pymongo import MongoClient

from src.application.form_submissions.ports import TelegramUserResolver
from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.outbox.handler_ids import (
    SALES_MONITORING_AUDIT_HANDLER_ID,
    SERVICE_VISIT_INCIDENT_HANDLER_ID,
)
from src.application.outbox.sales_monitoring_audit import SalesMonitoringAuditHandler
from src.application.outbox.service_visit_incident import ServiceVisitIncidentHandler
from src.application.reference_data import ReferenceDataProvider
from src.application.sales_monitoring import CatalogMachine
from src.application.sales_monitoring.no_sales_control import NoSalesVisitBlockLookup
from src.application.sales_monitoring.ports import SalesMonitoringAuditStore
from src.application.service_visits import (
    AlwaysAllowNoSalesVisitPolicy,
    ClearNoSalesIncident,
    ClearOfflineIncident,
    EnqueueVisitForceNotify,
    MachineNoSalesVisitPolicy,
    OpenServiceIncident,
    TechnicianDisplayLookup,
)
from src.application.service_visits.ports import ServiceVisitStore
from src.application.sheets.technician_locations import (
    find_technician_id_for_machine_in_snapshot,
    list_all_machines_from_snapshot,
)
from src.config.settings import Settings
from src.domain.ids import MachineId, TechnicianId
from src.domain.machine_sales import MachineSale
from src.domain.sales_monitoring.events import (
    SalesMonitoringNoSalesStaleCleared,
    SalesMonitoringNoSalesStaleOpened,
    SalesMonitoringOfflineCleared,
    SalesMonitoringOfflineOpened,
    SalesMonitoringTodayNoSales,
    SalesMonitoringYesterdayDecline,
    SalesMonitoringYesterdayNoSales,
)
from src.infrastructure.composition.adapters.assigned_technician_resolver import (
    ReferenceDataAssignedTechnicianResolver,
)
from src.infrastructure.composition.factories import (
    build_kitvending_request_id_store,
    build_machine_sales_qty_baseline_lookup,
)
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    subscribe_visit_force_notify,
)
from src.infrastructure.integrations.kitvending.platform_accounts import (
    KitPlatformAccount,
    accounts_file_is_valid,
    load_kit_platform_accounts,
)
from src.infrastructure.kitvending.deploy.client import KitVendingDeployClient
from src.infrastructure.mongodb.kitvending_request_ids import MongoDatabaseSource
from src.infrastructure.outbox import OutboxDomainEventPublisher, OutboxProcessorRegistry
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.rate_limiting import SyncGlobalBackoff, SyncRateLimiter
from src.infrastructure.sales_monitoring.kit_vm_states import HeadKitVmStatesReader


@beartype
@dataclass(slots=True)
class _SystemUtcClock:
    def now_utc_iso(self) -> str:
        return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


@beartype
class _InMemoryWorkerStatusRepository:
    def __init__(self) -> None:
        self.heartbeats: list[tuple[str, bool]] = []

    def record_heartbeat(self, *, at: str, enabled: bool) -> None:
        self.heartbeats.append((at, enabled))


@beartype
@dataclass(frozen=True, slots=True)
class MachineSalesForReportLoader:
    store: MachineSalesStore

    @beartype
    def load_for_report(
        self,
        *,
        machine_ids: Sequence[MachineId],
        opened_at: datetime,
        closed_at: datetime,
    ) -> tuple[MachineSale, ...]:
        sales: list[MachineSale] = []
        for machine_id in machine_ids:
            sales.extend(
                self.store.find_in_window(
                    machine_id,
                    opened_at=opened_at,
                    closed_at=closed_at,
                )
            )
        return tuple(sales)


@beartype
@dataclass(frozen=True, slots=True)
class SyncOutboxHandlerDrainer:
    worker: OutboxWorker

    @beartype
    def drain_handler(self, handler_id: str) -> int:
        return asyncio.run(self.worker.process_batch_for_handler(handler_id))


@beartype
@dataclass(frozen=True, slots=True)
class ReferenceDataTechnicianDisplayLookup:
    provider: ReferenceDataProvider

    @beartype
    def display_name(self, technician_id: TechnicianId) -> str | None:
        directory = self.provider.technicians_directory_or_none()
        if directory is None:
            return None
        name = directory.names_by_id.get(technician_id)
        if name is None:
            return None
        stripped = name.strip()
        return stripped or None


@beartype
def _register_sales_monitoring_audit(
    *,
    publisher: OutboxDomainEventPublisher,
    processors: OutboxProcessorRegistry,
    audit_store: SalesMonitoringAuditStore,
) -> None:
    handler = SalesMonitoringAuditHandler(audit_store=audit_store)
    processors.register(SALES_MONITORING_AUDIT_HANDLER_ID, handler.process)
    for event_type in (
        SalesMonitoringYesterdayNoSales,
        SalesMonitoringYesterdayDecline,
        SalesMonitoringTodayNoSales,
        SalesMonitoringOfflineOpened,
        SalesMonitoringOfflineCleared,
        SalesMonitoringNoSalesStaleOpened,
        SalesMonitoringNoSalesStaleCleared,
    ):
        publisher.subscribe(event_type, SALES_MONITORING_AUDIT_HANDLER_ID)


@beartype
def _register_service_visit_incident(
    *,
    publisher: OutboxDomainEventPublisher,
    processors: OutboxProcessorRegistry,
    store: ServiceVisitStore,
    sales: MachineSalesStore,
    timezone: ZoneInfo,
    baseline_timezone: ZoneInfo,
    day_end_hour: int,
    min_baseline_qty: Decimal,
    days_for_average: int,
    baseline_min_points: int,
    baseline_winsorize_min_points: int,
    baseline_winsorize_percent: int,
    visit_policy: MachineNoSalesVisitPolicy | None = None,
    control: NoSalesVisitBlockLookup | None = None,
    reference_provider: ReferenceDataProvider | None = None,
    telegram_users: TelegramUserResolver | None = None,
    technician_display: TechnicianDisplayLookup | None = None,
    task_notify_enabled: bool = False,
) -> None:
    resolved_policy = visit_policy if visit_policy is not None else AlwaysAllowNoSalesVisitPolicy()
    force_notify: EnqueueVisitForceNotify | None = None
    if (
        reference_provider is not None
        and telegram_users is not None
        and technician_display is not None
    ):
        force_notify = EnqueueVisitForceNotify(
            publisher=publisher,
            resolver=ReferenceDataAssignedTechnicianResolver(
                provider=reference_provider,
                telegram_users=telegram_users,
                display=technician_display,
            ),
            enabled=task_notify_enabled,
        )
        if task_notify_enabled:
            subscribe_visit_force_notify(publisher)
    handler = ServiceVisitIncidentHandler(
        opener=OpenServiceIncident(
            store=store,
            baseline_lookup=build_machine_sales_qty_baseline_lookup(
                sales=sales,
                timezone=baseline_timezone,
                days_for_average=days_for_average,
                baseline_min_points=baseline_min_points,
                baseline_winsorize_min_points=baseline_winsorize_min_points,
                baseline_winsorize_percent=baseline_winsorize_percent,
            ),
            min_baseline_qty=min_baseline_qty,
            visit_policy=resolved_policy,
        ),
        clearer=ClearOfflineIncident(store=store),
        no_sales_clearer=ClearNoSalesIncident(store=store),
        timezone=timezone,
        day_end_hour=day_end_hour,
        force_notify=force_notify,
        control=control,
    )
    processors.register(SERVICE_VISIT_INCIDENT_HANDLER_ID, handler.process)
    for event_type in (
        SalesMonitoringYesterdayNoSales,
        SalesMonitoringTodayNoSales,
        SalesMonitoringOfflineOpened,
        SalesMonitoringOfflineCleared,
        SalesMonitoringNoSalesStaleOpened,
        SalesMonitoringNoSalesStaleCleared,
    ):
        publisher.subscribe(event_type, SERVICE_VISIT_INCIDENT_HANDLER_ID)


@beartype
def _catalog_from_provider(provider: ReferenceDataProvider) -> tuple[CatalogMachine, ...]:
    snapshot = provider.coffee_locations()
    machines = list_all_machines_from_snapshot(snapshot)
    lookup = ReferenceDataTechnicianDisplayLookup(provider=provider)
    catalog: list[CatalogMachine] = []
    for machine in machines:
        tech_id = find_technician_id_for_machine_in_snapshot(snapshot, machine.id)
        display = lookup.display_name(tech_id) if tech_id is not None else None
        catalog.append(
            CatalogMachine(
                machine_id=machine.id,
                name=machine.name,
                assigned_technician_id=tech_id,
                assigned_technician_display=display,
            )
        )
    return tuple(catalog)


@beartype
def _build_head_kit_states_reader(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None,
    http_client: httpx.Client,
) -> tuple[HeadKitVmStatesReader, tuple[Callable[[], None], ...]]:
    kit = settings.kitvending
    if not accounts_file_is_valid(kit.accounts_path):
        raise ValueError(
            "KitVending accounts file required when SALES_MONITORING_WORKER_ENABLED=true",
        )
    accounts = load_kit_platform_accounts(kit.accounts_path)
    request_id_store = build_kitvending_request_id_store(
        settings,
        mongo_client=mongo_client,
    )

    def factory(account: KitPlatformAccount) -> KitVendingDeployClient:
        return KitVendingDeployClient(
            account=account,
            settings=kit,
            http_client=http_client,
            request_id_store=request_id_store,
            rate_limiter=SyncRateLimiter(
                max_requests=kit.requests_per_window,
                time_window=kit.window_seconds,
            ),
            backoff=SyncGlobalBackoff(timeout=kit.backoff_seconds),
        )

    reader = HeadKitVmStatesReader(accounts=accounts, deploy_client_factory=factory)
    return reader, (http_client.close,)
