from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import httpx
from beartype import beartype

from src.application.master_data import machine_ids_excluded_from_no_sales_monitoring
from src.application.reference_data import ReferenceDataProvider
from src.application.sales_monitoring import (
    CatalogMachine,
    EvaluateNoSalesStale,
    EventStoreLastMaintenanceByMachine,
    PublishNoSalesStatusBoard,
    RunOfflinePoll,
    RunSalesReport,
    parse_excluded_machine_codes,
    union_excluded_machine_codes,
)
from src.application.sales_monitoring.no_sales_control import NoSalesVisitBlockLookup
from src.application.sales_monitoring.ports import TechnicianDisplayLookup
from src.application.service_visits import (
    AlwaysAllowNoSalesVisitPolicy,
    MigrateDayBasedNoSalesVisits,
)
from src.config.settings import Settings
from src.infrastructure.composition.adapters.machine_sales_freshness_lookup import (
    MachineSalesStoreFreshnessLookup,
)
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.factories import (
    attach_location_roster,
    attach_master_data,
    attach_system_users,
    attach_technicians,
    build_event_store,
    build_location_roster_store,
    build_machine_sales_store,
    build_maintenance_cooldown_bypass_reader,
    build_master_data_stores,
    build_outbox_store,
    build_reference_data_snapshot_store,
    build_reference_data_sync,
    build_sales_monitoring_audit_store,
    build_service_visit_store,
    build_status_board_pointer_store,
    build_system_user_store,
    build_technician_store,
    build_telegram_user_resolver,
    warm_up_reference_data_provider,
)
from src.infrastructure.composition.sales_monitoring_worker_container import (
    SalesMonitoringWorkerContainer,
)
from src.infrastructure.composition.wiring.no_sales_detection_catalog import (
    NoSalesParkMachine,
    merge_no_sales_detection_catalog,
    status_board_catalog,
)
from src.infrastructure.composition.wiring.sales_monitoring_worker_adapters import (
    MachineSalesForReportLoader,
    ReferenceDataTechnicianDisplayLookup,
    SyncOutboxHandlerDrainer,
    _build_head_kit_states_reader,
    _catalog_from_provider,
    _InMemoryWorkerStatusRepository,
    _register_sales_monitoring_audit,
    _register_service_visit_incident,
    _SystemUtcClock,
)
from src.infrastructure.composition.wiring.wire_sales_sheet_export import (
    build_sales_sheet_export_tick,
)
from src.infrastructure.integrations.kitvending.http_client import KitVendingNetworkError
from src.infrastructure.outbox import OutboxDomainEventPublisher, OutboxProcessorRegistry
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.reference_data.master_machine_no_sales_visit_policy import (
    MasterMachineNoSalesVisitPolicy,
)
from src.infrastructure.sales_monitoring.cron_scheduler import SalesMonitoringCronScheduler
from src.infrastructure.sales_monitoring.mongo_worker_status import (
    MongoSalesMonitoringWorkerStatusRepository,
)
from src.infrastructure.sales_monitoring.telegram_notifiers import (
    TelegramSalesMonitoringAlertNotifier,
    TelegramSalesMonitoringReportNotifier,
)
from src.infrastructure.sales_monitoring.worker_runtime import SalesMonitoringWorkerRuntime

_logger = logging.getLogger(__name__)

_STATUS_BOARD_PUBLISH_LOCK = threading.Lock()


@beartype
def run_offline_poll_safely(*, execute: Callable[[], None]) -> None:
    try:
        execute()
    except KitVendingNetworkError:
        _logger.warning("sales_monitoring_offline_poll_kit_network")


def _safe_publish_status_board(
    publish: PublishNoSalesStatusBoard,
    *,
    mode: Literal["sync", "rotate"],
    catalog: Sequence[CatalogMachine],
    now: datetime,
    timezone: ZoneInfo,
    stale_hours: int,
    last_sale_lookup_days: int,
    operational_timezone: ZoneInfo,
    day_end_hour: int,
    excluded_codes: frozenset[str],
) -> None:
    with _STATUS_BOARD_PUBLISH_LOCK:
        try:
            publish.execute(
                mode=mode,
                catalog=catalog,
                now=now,
                timezone=timezone,
                stale_hours=stale_hours,
                last_sale_lookup_days=last_sale_lookup_days,
                operational_timezone=operational_timezone,
                day_end_hour=day_end_hour,
                excluded_codes=excluded_codes,
            )
        except Exception:
            _logger.exception("status_board_publish_failed mode=%s", mode)


# Re-export for tests that monkeypatch wire module symbols.
__all__ = (
    "MachineSalesForReportLoader",
    "ReferenceDataTechnicianDisplayLookup",
    "SyncOutboxHandlerDrainer",
    "_InMemoryWorkerStatusRepository",
    "_SystemUtcClock",
    "_build_head_kit_states_reader",
    "_catalog_from_provider",
    "_register_sales_monitoring_audit",
    "_register_service_visit_incident",
    "wire_sales_monitoring_worker",
)


@beartype
@dataclass(frozen=True, slots=True)
class _EnabledJobBundle:
    compare_callback: Callable[[], None]
    today_callback: Callable[[], None]
    offline_callback: Callable[[], None]
    no_sales_stale_callback: Callable[[], None]
    status_board_rotate_callback: Callable[[], None]
    export_callback: Callable[[], None] | None
    closers: tuple[Callable[[], None], ...]
    processors: OutboxProcessorRegistry


@beartype
def _build_enabled_job_bundle(
    settings: Settings,
    *,
    persistence: PersistenceBundle,
    publisher: OutboxDomainEventPublisher,
    processors: OutboxProcessorRegistry,
) -> _EnabledJobBundle:
    mongo_client = persistence.mongo_client
    assert mongo_client is not None

    audit_store = build_sales_monitoring_audit_store(settings, client=mongo_client)
    _register_sales_monitoring_audit(
        publisher=publisher,
        processors=processors,
        audit_store=audit_store,
    )

    event_store = build_event_store(settings, client=mongo_client)
    last_maintenance = EventStoreLastMaintenanceByMachine(event_store=event_store)
    machine_sales_store = build_machine_sales_store(settings, client=mongo_client)
    visit_store = build_service_visit_store(settings, client=mongo_client)
    sales_loader = MachineSalesForReportLoader(store=machine_sales_store)

    reference_store = build_reference_data_snapshot_store(settings, client=mongo_client)
    provider = ReferenceDataProvider()
    reference_sync = build_reference_data_sync(
        settings,
        store=reference_store,
        provider=provider,
    )
    roster_store = build_location_roster_store(settings, client=mongo_client)
    attach_location_roster(
        provider,
        settings,
        roster_store=roster_store,
        snapshot_store=reference_store,
        now=datetime.now(UTC),
    )
    master_data_stores = build_master_data_stores(settings, mongo_client=mongo_client)
    attach_master_data(
        provider,
        stores=master_data_stores,
        enabled=settings.master_data.enabled,
    )
    visit_policy = (
        MasterMachineNoSalesVisitPolicy(master_data_stores.machines)
        if settings.master_data.enabled
        else AlwaysAllowNoSalesVisitPolicy()
    )
    technician_store = build_technician_store(settings, mongo_client=mongo_client)
    attach_technicians(
        provider,
        store=technician_store,
        enabled=settings.master_data.technicians_enabled,
    )
    system_user_store = build_system_user_store(settings, mongo_client=mongo_client)
    attach_system_users(
        provider,
        store=system_user_store,
        enabled=settings.master_data.users_enabled,
    )
    technician_display: TechnicianDisplayLookup = ReferenceDataTechnicianDisplayLookup(
        provider=provider,
    )
    telegram_users = build_telegram_user_resolver(provider)
    _register_service_visit_incident(
        publisher=publisher,
        processors=processors,
        store=visit_store,
        sales=machine_sales_store,
        timezone=settings.service_calendar.zone_info(),
        baseline_timezone=ZoneInfo(settings.sales_monitoring.tz),
        day_end_hour=settings.service_calendar.service_day_end_hour,
        min_baseline_qty=settings.service_visits.no_sales_min_baseline_qty,
        days_for_average=settings.sales_monitoring.days_for_average,
        baseline_min_points=settings.sales_monitoring.baseline_min_points,
        baseline_winsorize_min_points=settings.sales_monitoring.baseline_winsorize_min_points,
        baseline_winsorize_percent=settings.sales_monitoring.baseline_winsorize_percent,
        visit_policy=visit_policy,
        control=(audit_store if isinstance(audit_store, NoSalesVisitBlockLookup) else None),
        reference_provider=provider,
        telegram_users=telegram_users,
        technician_display=technician_display,
        task_notify_enabled=settings.service_visits.task_notify_enabled,
    )

    http_client = httpx.Client(timeout=60.0)
    kit_states, kit_closers = _build_head_kit_states_reader(
        settings,
        mongo_client=mongo_client,
        http_client=http_client,
    )

    sm = settings.sales_monitoring
    report_token = sm.telegram_bot_token
    assert report_token is not None
    assert sm.telegram_chat_id is not None
    assert sm.decline_telegram_chat_id is not None
    assert sm.alert_telegram_chat_id is not None
    alert_token = sm.alert_telegram_bot_token or report_token
    decline_notifier = TelegramSalesMonitoringReportNotifier(
        bot_token=report_token.get_secret_value(),
        chat_id=sm.decline_telegram_chat_id,
    )
    board_telegram = TelegramSalesMonitoringReportNotifier(
        bot_token=report_token.get_secret_value(),
        chat_id=sm.telegram_chat_id,
    )
    alert_notifier = TelegramSalesMonitoringAlertNotifier(
        bot_token=alert_token.get_secret_value(),
        chat_id=sm.alert_telegram_chat_id,
    )

    outbox_worker = OutboxWorker(
        store=publisher.store,
        processors=processors,
        poll_interval_seconds=settings.mongodb.outbox_poll_interval_seconds,
    )
    drainer = SyncOutboxHandlerDrainer(worker=outbox_worker)

    offline_poll = RunOfflinePoll(
        kit_states=kit_states,
        audit_store=audit_store,
        publisher=publisher,
        drainer=drainer,
        alert_notifier=alert_notifier,
    )
    sales_report = RunSalesReport(
        sales_loader=sales_loader,
        last_maintenance=last_maintenance,
        technician_display=technician_display,
        publisher=publisher,
        drainer=drainer,
        decline_notifier=decline_notifier,
    )
    migrate_day_based_no_sales = MigrateDayBasedNoSalesVisits(store=visit_store)
    freshness = MachineSalesStoreFreshnessLookup(
        store=machine_sales_store,
        last_sale_lookup_days=sm.last_sale_lookup_days,
    )
    bypass_reader = build_maintenance_cooldown_bypass_reader(
        settings,
        client=mongo_client,
    )
    evaluate_no_sales_stale = EvaluateNoSalesStale(
        publisher=publisher,
        audit_store=audit_store,
        freshness=freshness,
        drainer=drainer,
        bypass_reader=bypass_reader,
    )
    pointer_store = build_status_board_pointer_store(settings, client=mongo_client)
    publish_status_board = PublishNoSalesStatusBoard(
        audit_store=audit_store,
        pointer_store=pointer_store,
        telegram=board_telegram,
        freshness=freshness,
        chat_id=sm.telegram_chat_id,
    )

    timezone = ZoneInfo(sm.tz)
    csv_excluded = parse_excluded_machine_codes(sm.excluded_machine_codes)

    def _prepare_catalog() -> tuple[CatalogMachine, ...]:
        warm_up_reference_data_provider(
            provider=provider,
            store=reference_store,
            sync=reference_sync,
        )
        attach_location_roster(
            provider,
            settings,
            roster_store=roster_store,
            snapshot_store=reference_store,
            now=datetime.now(UTC),
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
        return _catalog_from_provider(provider)

    def _excluded_codes() -> frozenset[str]:
        ui_excluded: frozenset[str] = frozenset()
        if settings.master_data.enabled:
            ui_excluded = machine_ids_excluded_from_no_sales_monitoring(
                master_data_stores.machines.list_all(),
            )
        return union_excluded_machine_codes(csv_excluded, ui_excluded)

    def _park_machines() -> tuple[NoSalesParkMachine, ...]:
        if not settings.master_data.enabled:
            return ()
        return tuple(
            NoSalesParkMachine(
                machine_id=machine.machine_id,
                kind=machine.kind.value,
                status=machine.status.value,
                name=machine.label or machine.machine_id.value,
            )
            for machine in master_data_stores.machines.list_all()
        )

    def compare_callback() -> None:
        now = datetime.now(timezone)
        report_day = now.date() - timedelta(days=1)
        sales_report.execute(
            catalog=_prepare_catalog(),
            excluded_codes=_excluded_codes(),
            report_day=report_day,
            branch="yesterday",
            now=now,
            timezone=timezone,
            days_for_average=sm.days_for_average,
            sales_drop_percent=sm.sales_drop_percent,
            sales_lookback_days=sm.last_sale_lookup_days,
            baseline_min_points=sm.baseline_min_points,
            baseline_winsorize_min_points=sm.baseline_winsorize_min_points,
            baseline_winsorize_percent=sm.baseline_winsorize_percent,
            no_sales_habitual_max_nonempty=sm.no_sales_habitual_max_nonempty,
        )

    def today_callback() -> None:
        now = datetime.now(timezone)
        report_day: date = now.date()
        sales_report.execute(
            catalog=_prepare_catalog(),
            excluded_codes=_excluded_codes(),
            report_day=report_day,
            branch="today",
            now=now,
            timezone=timezone,
            days_for_average=sm.days_for_average,
            sales_drop_percent=sm.sales_drop_percent,
            sales_lookback_days=sm.last_sale_lookup_days,
            baseline_min_points=sm.baseline_min_points,
            baseline_winsorize_min_points=sm.baseline_winsorize_min_points,
            baseline_winsorize_percent=sm.baseline_winsorize_percent,
            no_sales_habitual_max_nonempty=sm.no_sales_habitual_max_nonempty,
        )

    def offline_callback() -> None:
        now = datetime.now(timezone)
        catalog = _prepare_catalog()
        assigned = {
            entry.machine_id: (
                entry.assigned_technician_id,
                entry.assigned_technician_display,
            )
            for entry in catalog
        }

        def _execute_offline_poll() -> None:
            offline_poll.execute(
                catalog_machine_ids=tuple(entry.machine_id for entry in catalog),
                excluded_codes=_excluded_codes(),
                now=now,
                threshold_minutes=sm.offline_ping_threshold_minutes,
                assigned_by_machine=assigned,
                last_maintenance=last_maintenance,
                technician_display=technician_display,
            )

        run_offline_poll_safely(execute=_execute_offline_poll)

    def no_sales_stale_callback() -> None:
        now = datetime.now(timezone)
        coffee = _prepare_catalog()
        detection = merge_no_sales_detection_catalog(coffee, _park_machines())
        assigned = {
            entry.machine_id: (
                entry.assigned_technician_id,
                entry.assigned_technician_display,
            )
            for entry in detection
        }
        try:
            migrate_day_based_no_sales.execute(now=now)
            evaluate_no_sales_stale.execute(
                catalog_machine_ids=tuple(entry.machine_id for entry in detection),
                excluded_codes=_excluded_codes(),
                now=now,
                stale_hours=sm.no_sales_stale_hours,
                max_lag_minutes=sm.no_sales_ingest_cursor_max_lag_minutes,
                last_sale_lookup_days=sm.last_sale_lookup_days,
                assigned_by_machine=assigned,
                last_maintenance=last_maintenance,
                technician_display=technician_display,
            )
        except Exception:
            _logger.exception("no_sales_stale_eval_failed")
            return
        _safe_publish_status_board(
            publish_status_board,
            mode="sync",
            catalog=status_board_catalog(coffee),
            now=now,
            timezone=timezone,
            stale_hours=sm.no_sales_stale_hours,
            last_sale_lookup_days=sm.last_sale_lookup_days,
            operational_timezone=settings.service_calendar.zone_info(),
            day_end_hour=settings.service_calendar.service_day_end_hour,
            excluded_codes=_excluded_codes(),
        )

    def status_board_rotate_callback() -> None:
        now = datetime.now(timezone)
        coffee = _prepare_catalog()
        detection = merge_no_sales_detection_catalog(coffee, _park_machines())
        assigned = {
            entry.machine_id: (
                entry.assigned_technician_id,
                entry.assigned_technician_display,
            )
            for entry in detection
        }
        try:
            migrate_day_based_no_sales.execute(now=now)
            evaluate_no_sales_stale.execute(
                catalog_machine_ids=tuple(entry.machine_id for entry in detection),
                excluded_codes=_excluded_codes(),
                now=now,
                stale_hours=sm.no_sales_stale_hours,
                max_lag_minutes=sm.no_sales_ingest_cursor_max_lag_minutes,
                last_sale_lookup_days=sm.last_sale_lookup_days,
                assigned_by_machine=assigned,
                last_maintenance=last_maintenance,
                technician_display=technician_display,
            )
        except Exception:
            _logger.exception("no_sales_stale_eval_failed")
            return
        _safe_publish_status_board(
            publish_status_board,
            mode="rotate",
            catalog=status_board_catalog(coffee),
            now=now,
            timezone=timezone,
            stale_hours=sm.no_sales_stale_hours,
            last_sale_lookup_days=sm.last_sale_lookup_days,
            operational_timezone=settings.service_calendar.zone_info(),
            day_end_hour=settings.service_calendar.service_day_end_hour,
            excluded_codes=_excluded_codes(),
        )

    export_callback = build_sales_sheet_export_tick(
        settings,
        mongo_client=mongo_client,
        reference_data_provider=provider,
        reference_store=reference_store,
        reference_sync=reference_sync,
        alert_notifier=alert_notifier,
    )

    return _EnabledJobBundle(
        compare_callback=compare_callback,
        today_callback=today_callback,
        offline_callback=offline_callback,
        no_sales_stale_callback=no_sales_stale_callback,
        status_board_rotate_callback=status_board_rotate_callback,
        export_callback=export_callback,
        closers=kit_closers,
        processors=processors,
    )


@beartype
def wire_sales_monitoring_worker(
    settings: Settings,
    *,
    persistence: PersistenceBundle,
) -> SalesMonitoringWorkerContainer:
    enabled = settings.sales_monitoring.worker_enabled
    mongo_client = persistence.mongo_client

    if enabled and (mongo_client is None or not settings.mongodb.is_configured):
        raise ValueError(
            "SALES_MONITORING_WORKER_ENABLED=true requires a configured MongoDB client",
        )

    if mongo_client is not None and settings.mongodb.is_configured:
        status_repository: (
            MongoSalesMonitoringWorkerStatusRepository | _InMemoryWorkerStatusRepository
        ) = MongoSalesMonitoringWorkerStatusRepository.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
    else:
        status_repository = _InMemoryWorkerStatusRepository()

    clock = _SystemUtcClock()
    extra_closers: tuple[Callable[[], None], ...] = ()
    outbox_processors: OutboxProcessorRegistry | None = None
    sm = settings.sales_monitoring
    timezone = ZoneInfo(sm.tz)
    export_callback: Callable[[], None] | None = None

    if enabled:
        if not settings.google_sheets.is_technicians_directory_configured:
            raise ValueError(
                "TECHNICIANS_DIRECTORY_SPREADSHEET_ID and "
                "TECHNICIANS_DIRECTORY_SHEET_ID must be set for sales-monitoring-worker",
            )
        assert mongo_client is not None
        outbox_store = build_outbox_store(settings, client=mongo_client)
        processors = OutboxProcessorRegistry()
        publisher = OutboxDomainEventPublisher(store=outbox_store)
        bundle = _build_enabled_job_bundle(
            settings,
            persistence=persistence,
            publisher=publisher,
            processors=processors,
        )
        extra_closers = bundle.closers
        outbox_processors = bundle.processors
        compare_callback = bundle.compare_callback
        today_callback = bundle.today_callback
        offline_callback = bundle.offline_callback
        no_sales_stale_callback = bundle.no_sales_stale_callback
        status_board_rotate_callback = bundle.status_board_rotate_callback
        export_callback = bundle.export_callback
    else:

        def compare_callback() -> None:
            return None

        def today_callback() -> None:
            return None

        def offline_callback() -> None:
            return None

        def no_sales_stale_callback() -> None:
            return None

        def status_board_rotate_callback() -> None:
            return None

    scheduler = SalesMonitoringCronScheduler(
        enabled=enabled,
        timezone=timezone,
        report_compare_cron=sm.report_compare_cron,
        report_today_cron=sm.report_today_cron,
        offline_poll_interval_minutes=sm.offline_poll_interval_minutes,
        offline_poll_from_hour=sm.offline_poll_from_hour,
        offline_poll_to_hour=sm.offline_poll_to_hour,
        no_sales_eval_interval_minutes=sm.no_sales_eval_interval_minutes,
        compare_callback=compare_callback,
        today_callback=today_callback,
        offline_callback=offline_callback,
        no_sales_stale_callback=no_sales_stale_callback,
        sales_sheet_export_enabled=sm.sales_sheet_export_enabled,
        sales_sheet_export_cron=sm.sales_sheet_export_cron,
        export_callback=export_callback,
        status_board_cron=sm.status_board_cron,
        status_board_rotate_callback=status_board_rotate_callback,
    )
    runtime = SalesMonitoringWorkerRuntime(
        enabled=enabled,
        status_repository=status_repository,
        scheduler=scheduler,
        clock=clock,
    )
    return SalesMonitoringWorkerContainer(
        runtime=runtime,
        persistence=persistence,
        extra_closers=extra_closers,
        outbox_processors=outbox_processors,
    )
