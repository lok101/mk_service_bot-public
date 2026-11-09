from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from beartype import beartype
from pymongo import MongoClient

from src.application.matrix_automation import (
    ApplySnackMatrix,
    MatrixDeployPayload,
    MatrixDeployResult,
    MatrixReferenceDataProvider,
    RunDailyMatrixDeployJob,
)
from src.application.matrix_automation.ports import (
    MatrixBaseMarginStore,
    MatrixDeployer,
    MatrixPriceSnapshotStore,
    MatrixStockProvider,
    MatrixWorkerStatusRepository,
    PurchaseAttributesReader,
    RunMatrixDeployBuildPort,
    SnackMachineLayoutStore,
)
from src.application.snack_loading import KitMatrixDeployMapStore, record_kit_matrix_deploy
from src.config.settings import Settings
from src.infrastructure.composition.bundles.persistence import PersistenceBundle
from src.infrastructure.composition.factories import (
    build_company_store,
    build_kitvending_request_id_store,
    build_matrix_base_margin_store,
    build_matrix_deployer,
    build_matrix_sku_catalog_store,
    build_matrix_snapshot_store,
    build_reference_data_snapshot_store,
)
from src.infrastructure.composition.matrix_automation_factory import (
    build_matrix_reference_data_provider,
    build_matrix_reference_sync,
)
from src.infrastructure.composition.matrix_worker_container import MatrixWorkerContainer
from src.infrastructure.composition.wiring.matrix_worker_fakes import (
    NoOpMatrixWorkerStatusRepository,  # re-export for tests/CLI  # noqa: F401
    _EmptyPurchaseClient,
    _InMemoryWorkerStatusRepository,
    _JobLoggerAdapter,
    _SystemUtcClock,
)
from src.infrastructure.composition.wiring.provider_backed_run_build import (
    ProviderBackedRunMatrixDeployBuild,
)
from src.infrastructure.integrations.kitvending.request_id_store import (
    KitVendingRequestIdStore,
)
from src.infrastructure.matrix_automation.cron_scheduler import MatrixCronScheduler
from src.infrastructure.matrix_automation.mongo_jobs import MongoMatrixDeployJobRepository
from src.infrastructure.matrix_automation.mongo_worker_status import (
    MongoMatrixWorkerStatusRepository,
)
from src.infrastructure.matrix_automation.sheets_reader import MatrixCatalogSheetsReader
from src.infrastructure.matrix_automation.telegram_notifier import MatrixJobTelegramNotifier
from src.infrastructure.matrix_automation.worker_runtime import MatrixWorkerRuntime
from src.infrastructure.mongodb.connection import MongoDatabaseSource
from src.infrastructure.mongodb.kit_matrix_deploy_map import MongoKitMatrixDeployMapStore
from src.infrastructure.moysklad.purchase_prices.reader import MoySkladPurchaseAttributesReader


@beartype
def build_matrix_catalog_reader(settings: Settings) -> MatrixCatalogSheetsReader:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    from src.infrastructure.integrations.google.sheets.sheet_reader import (
        GOOGLE_SHEETS_READONLY_SCOPE,
    )

    matrix = settings.matrix_automation
    credentials_file = settings.google_sheets.credentials_file.strip()
    spreadsheet_id = matrix.google_sheets_spreadsheet_id.strip()
    exclude: set[int] = set()
    if matrix.product_multipliers_sheet_id is not None:
        exclude.add(matrix.product_multipliers_sheet_id)

    def _service() -> Any:
        credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            credentials_file,
            scopes=[GOOGLE_SHEETS_READONLY_SCOPE],
        )
        return build("sheets", "v4", credentials=credentials)

    def fetch_metadata() -> dict[str, Any]:
        service = _service()
        try:
            raw = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        finally:
            service.close()
        if not isinstance(raw, dict):
            raise ValueError("Spreadsheet metadata must be an object")
        return raw

    def fetch_values_by_title(title: str) -> list[list[Any]]:
        service = _service()
        try:
            raw_values = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=f"'{title}'")
                .execute()
            )
        finally:
            service.close()
        values = raw_values.get("values", [])
        if not isinstance(values, list):
            raise ValueError("Sheet values must be a list")
        return [row for row in values if isinstance(row, list)]

    return MatrixCatalogSheetsReader(
        credentials_file=credentials_file,
        spreadsheet_id=spreadsheet_id,
        exclude_sheet_ids=exclude,
        fetch_metadata=fetch_metadata,
        fetch_values_by_title=fetch_values_by_title,
    )


@beartype
def build_purchase_attributes_reader(
    settings: Settings,
) -> tuple[PurchaseAttributesReader, Callable[[], None]]:
    """Matrix-worker has no Remap HTTP (ADR-0083); buy prices come via effects mirror."""
    _ = settings
    return MoySkladPurchaseAttributesReader(client=_EmptyPurchaseClient()), lambda: None


@beartype
@dataclass(slots=True)
class MatrixDeployJobBundle:
    daily_job: RunDailyMatrixDeployJob
    closers: tuple[Callable[[], None], ...]


@beartype
@dataclass(slots=True)
class _DeployMapRecordingDeployer:
    inner: MatrixDeployer
    store: KitMatrixDeployMapStore

    @beartype
    def deploy(self, payloads: list[MatrixDeployPayload]) -> list[MatrixDeployResult]:
        results = self.inner.deploy(payloads)
        for result in results:
            record_kit_matrix_deploy(
                self.store,
                result=result,
                vending_machine_id=result.vending_machine_id,
                kit_matrix_name=result.kit_matrix_name,
            )
        return results


@beartype
def wrap_deployer_with_deploy_map(
    inner: MatrixDeployer,
    store: KitMatrixDeployMapStore,
) -> MatrixDeployer:
    return _DeployMapRecordingDeployer(inner=inner, store=store)


@beartype
def build_matrix_deploy_job_bundle(
    settings: Settings,
    *,
    persistence: PersistenceBundle,
    request_id_store: KitVendingRequestIdStore,
    stock_provider: MatrixStockProvider | None = None,
    deploy_map_store: KitMatrixDeployMapStore | None = None,
    seed_only: bool = False,
    trigger: Literal["seed", "cron", "admin_apply"] = "cron",
    status_repository: MatrixWorkerStatusRepository,
) -> MatrixDeployJobBundle:
    matrix = settings.matrix_automation
    mongo_client = persistence.mongo_client
    if mongo_client is None or not settings.mongodb.is_configured:
        raise ValueError("matrix deploy job bundle requires configured MongoDB client")
    store = build_reference_data_snapshot_store(settings, client=mongo_client)
    provider = build_matrix_reference_data_provider(matrix)
    catalog_reader = build_matrix_catalog_reader(settings)
    matrix_sync = build_matrix_reference_sync(
        settings,
        store=store,
        provider=provider,
        catalog_reader=catalog_reader,
        client=mongo_client,
    )
    snapshot_store = build_matrix_snapshot_store(settings, client=mongo_client)
    purchase_reader, purchase_close = build_purchase_attributes_reader(settings)
    run_build = build_provider_backed_run_build(
        settings,
        snapshot_store=snapshot_store,
        purchase_reader=purchase_reader,
        provider=provider,
        stock_provider=stock_provider,
        client=mongo_client,
    )
    company_store = build_company_store(settings, mongo_client=mongo_client)
    deployer: MatrixDeployer = build_matrix_deployer(
        settings,
        request_id_store=request_id_store,
        company_store=company_store,
    )
    resolved_deploy_map = deploy_map_store
    if resolved_deploy_map is None:
        resolved_deploy_map = MongoKitMatrixDeployMapStore.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
    deployer = wrap_deployer_with_deploy_map(deployer, resolved_deploy_map)
    job_repository = MongoMatrixDeployJobRepository.from_settings(
        settings.mongodb,
        client=mongo_client,
    )
    alert_chat_id = settings.telegram.alert_chat_id
    if alert_chat_id is None:
        raise ValueError("TELEGRAM_ALERT_CHAT_ID is required for matrix deploy job bundle")
    notifier = MatrixJobTelegramNotifier(
        bot_token=settings.telegram.bot_token.get_secret_value().strip(),
        chat_id=alert_chat_id,
        max_price_delta_pct=matrix.max_price_delta_pct,
        kept_alert_pct=matrix.kept_alert_pct,
    )
    daily_job = RunDailyMatrixDeployJob(
        matrix_sync=matrix_sync,
        run_build=run_build,
        deployer=deployer,
        job_repository=job_repository,
        snapshot_store=snapshot_store,
        status_repository=status_repository,
        notifier=notifier,
        clock=_SystemUtcClock(),
        id_factory=lambda: str(uuid.uuid4()),
        logger=_JobLoggerAdapter(logging.getLogger("matrix_worker")),
        seed_only=seed_only,
        trigger=trigger,
    )
    return MatrixDeployJobBundle(daily_job=daily_job, closers=(purchase_close,))


@beartype
def build_provider_backed_run_build(
    settings: Settings,
    *,
    snapshot_store: MatrixPriceSnapshotStore,
    purchase_reader: PurchaseAttributesReader,
    provider: MatrixReferenceDataProvider,
    stock_provider: MatrixStockProvider | None = None,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
) -> RunMatrixDeployBuildPort:
    matrix = settings.matrix_automation
    sku_catalog_master_enabled = matrix.sku_catalog_master_enabled
    sku_catalog_store = None
    if sku_catalog_master_enabled:
        sku_catalog_store = build_matrix_sku_catalog_store(settings, client=client)
    base_margin_store = build_matrix_base_margin_store(settings, client=client)
    return ProviderBackedRunMatrixDeployBuild(
        snapshot_store=snapshot_store,
        purchase_reader=purchase_reader,
        provider=provider,
        blocking_cell_price=matrix.blocking_cell_price,
        max_price_delta_pct=matrix.max_price_delta_pct,
        substitution_guard_enabled=matrix.substitution_guard_enabled,
        stock_provider=stock_provider,
        base_margin_store=base_margin_store,
        sku_catalog_master_enabled=sku_catalog_master_enabled,
        sku_catalog_store=sku_catalog_store,
    )


@beartype
def build_admin_apply_snack_matrix(
    settings: Settings,
    *,
    snack_layout_store: SnackMachineLayoutStore,
    snapshot_store: MatrixPriceSnapshotStore,
    purchase_reader: PurchaseAttributesReader,
    base_margin_store: MatrixBaseMarginStore,
    provider: MatrixReferenceDataProvider,
    client: MongoClient[dict[str, Any]] | MongoDatabaseSource | None = None,
    deploy_map_store: KitMatrixDeployMapStore | None = None,
    request_id_store: KitVendingRequestIdStore | None = None,
) -> ApplySnackMatrix:
    mongo_client = client
    run_build = build_provider_backed_run_build(
        settings,
        snapshot_store=snapshot_store,
        purchase_reader=purchase_reader,
        provider=provider,
        stock_provider=None,
        client=mongo_client,
    )
    resolved_request_id_store = request_id_store
    if resolved_request_id_store is None:
        if mongo_client is None:
            raise ValueError("Mongo client required to build admin apply snack matrix")
        resolved_request_id_store = build_kitvending_request_id_store(
            settings,
            mongo_client=mongo_client,
        )
    company_store = build_company_store(settings, mongo_client=mongo_client)
    deployer: MatrixDeployer = build_matrix_deployer(
        settings,
        request_id_store=resolved_request_id_store,
        company_store=company_store,
    )
    resolved_deploy_map = deploy_map_store
    if resolved_deploy_map is None:
        if mongo_client is None:
            raise ValueError("Mongo client required to build admin apply snack matrix deploy map")
        resolved_deploy_map = MongoKitMatrixDeployMapStore.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
    deployer = wrap_deployer_with_deploy_map(deployer, resolved_deploy_map)
    if mongo_client is None:
        raise ValueError("Mongo client required to build admin apply snack matrix job repository")
    job_repository = MongoMatrixDeployJobRepository.from_settings(
        settings.mongodb,
        client=mongo_client,
    )
    return ApplySnackMatrix(
        layouts=snack_layout_store,
        base_margin_store=base_margin_store,
        snapshots=snapshot_store,
        deployer=deployer,
        run_build=run_build,
        job_repository=job_repository,
        clock=_SystemUtcClock(),
        id_factory=lambda: str(uuid.uuid4()),
    )


@beartype
def wire_matrix_worker(
    settings: Settings,
    *,
    persistence: PersistenceBundle,
    stock_provider: MatrixStockProvider | None = None,
    deploy_map_store: KitMatrixDeployMapStore | None = None,
) -> MatrixWorkerContainer:
    matrix = settings.matrix_automation
    if matrix.substitution_guard_enabled and stock_provider is None:
        raise ValueError("MatrixStockProvider required when MATRIX_SUBSTITUTION_GUARD_ENABLED=true")
    enabled = matrix.worker_enabled
    mongo_client = persistence.mongo_client

    if enabled and (mongo_client is None or not settings.mongodb.is_configured):
        msg = "MATRIX_WORKER_ENABLED=true requires a configured MongoDB client"
        raise ValueError(msg)

    status_repository: MatrixWorkerStatusRepository
    if mongo_client is not None and settings.mongodb.is_configured:
        status_repository = MongoMatrixWorkerStatusRepository.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
    else:
        status_repository = _InMemoryWorkerStatusRepository()

    clock = _SystemUtcClock()
    job_callback: Callable[[], None]
    extra_closers: tuple[Callable[[], None], ...] = ()

    if enabled:
        request_id_store = build_kitvending_request_id_store(
            settings,
            mongo_client=mongo_client,
        )
        bundle = build_matrix_deploy_job_bundle(
            settings,
            persistence=persistence,
            request_id_store=request_id_store,
            stock_provider=stock_provider,
            deploy_map_store=deploy_map_store,
            seed_only=False,
            trigger="cron",
            status_repository=status_repository,
        )
        extra_closers = bundle.closers
        daily_job = bundle.daily_job

        def job_callback() -> None:
            daily_job.run()
    else:

        def job_callback() -> None:
            return None

    scheduler = MatrixCronScheduler(
        enabled=enabled,
        hour=matrix.worker_cron_hour,
        timezone=settings.service_calendar.zone_info(),
        callback=job_callback,
    )
    runtime = MatrixWorkerRuntime(
        enabled=enabled,
        status_repository=status_repository,
        scheduler=scheduler,
        clock=clock,
    )
    return MatrixWorkerContainer(
        runtime=runtime,
        persistence=persistence,
        extra_closers=extra_closers,
    )
