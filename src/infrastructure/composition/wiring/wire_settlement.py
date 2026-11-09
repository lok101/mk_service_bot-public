from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions.ports import (
    FormSubmissionStore,
)
from src.application.inventory_reconciliation.close_period import (
    CloseResponsibilityPeriodOnRevision,
)
from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancyStore,
)
from src.application.inventory_reconciliation.discover_kitshop_sales import DiscoverKitShopSales
from src.application.inventory_reconciliation.drain_kitshop_sales import (
    DrainKitShopSalesBacklog,
    KitShopSaleAlertNotifier,
    NoOpKitShopSaleAlertNotifier,
)
from src.application.inventory_reconciliation.import_sales import ImportKitVendingSales
from src.application.inventory_reconciliation.ports import (
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.machine_operations.ports import EventStore, VendingMachineRepository
from src.application.micromarket_loading import ApplyMicromarketSaleToStock
from src.application.product_identity.ports import DomainProductStore
from src.application.reference_data import ReferenceDataProvider
from src.application.snack_loading import (
    NoOpSnackSaleUnresolvedAlertNotifier,
    SnackSaleUnresolvedAlertNotifier,
)
from src.application.snack_loading.ports import (
    KitMatrixDeployMapStore,
    SnackMachineStockStore,
)
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.config.settings import Settings
from src.infrastructure.alerting.kitshop_sale_alert_notifier import (
    TelegramKitShopSaleAlertNotifier,
)
from src.infrastructure.alerting.sale_resolve_hold_notifier import (
    NoOpSaleResolveHoldAlertNotifier,
    SaleResolveHoldAlertNotifier,
    TelegramSaleResolveHoldAlertNotifier,
)
from src.infrastructure.alerting.snack_sale_unresolved_notifier import (
    TelegramSnackSaleUnresolvedAlertNotifier,
)
from src.infrastructure.composition.adapters.kitshop_company_resolver import (
    KitShopCompanyIdResolverAdapter,
)
from src.infrastructure.composition.adapters.kitshop_sales_gateway import (
    KitShopSalesGatewayAdapter,
)
from src.infrastructure.composition.adapters.period_party_names import (
    VendingMachinePeriodPartyNamesLookup,
)
from src.infrastructure.composition.bundles.settlement import SettlementBundle
from src.infrastructure.composition.factories import (
    build_apply_snack_sale,
    build_coffee_recipe_repository,
    build_company_store,
    build_kitshop_client,
    build_kitvending_client,
    build_kitvending_request_id_store,
    build_machine_sale_skip_store,
    build_machine_sales_store,
    build_moysklad_client,
    build_period_reconciliation_repository,
    build_refresh_pending_with_accountability,
    build_technician_settlement_repository,
)
from src.infrastructure.composition.factories.company_directory import (
    build_kit_company_directory,
)
from src.infrastructure.composition.factories.integrations import (
    build_kitshop_reference_snapshot_store,
)
from src.infrastructure.composition.factories.product_identity import (
    build_domain_product_kit_shop_resolver,
    build_domain_product_resolver,
)
from src.infrastructure.integrations.kitshop.client import KitShopHttpClient
from src.infrastructure.integrations.kitshop.matrix_gateway import KitShopMatrixGateway
from src.infrastructure.integrations.moysklad.client import MoySkladClient
from src.infrastructure.kitshop_reference_snapshot_worker import (
    KitShopReferenceSnapshotWorker,
)
from src.infrastructure.kitshop_sales_ingest_worker import KitShopSalesIngestWorker
from src.infrastructure.machine_revision_history import EventStoreMachineRevisionHistoryReader
from src.infrastructure.mongodb.kitshop_sale_receipts import MongoKitShopSaleReceiptStore
from src.infrastructure.mongodb.kitshop_sales_backlog import MongoKitShopSalesBacklogStore
from src.infrastructure.mongodb.kitshop_sales_ingest_cursors import (
    MongoKitShopSalesIngestCursorStore,
)
from src.infrastructure.sales_ingest_worker import SalesIngestWorker

_LOGGER = logging.getLogger(__name__)


@beartype
def _build_unresolved_alert_notifier(
    settings: Settings,
) -> SnackSaleUnresolvedAlertNotifier:
    chat_id = settings.telegram.alert_chat_id
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if chat_id is None or not bot_token:
        return NoOpSnackSaleUnresolvedAlertNotifier()
    return TelegramSnackSaleUnresolvedAlertNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
    )


@beartype
def _build_kitshop_sale_alert_notifier(
    settings: Settings,
) -> KitShopSaleAlertNotifier:
    chat_id = settings.telegram.alert_chat_id
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if chat_id is None or not bot_token:
        return NoOpKitShopSaleAlertNotifier()
    return TelegramKitShopSaleAlertNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        cooldown_minutes=settings.kitshop.sale_alert_cooldown_minutes,
    )


@beartype
def _build_sale_resolve_hold_notifier(
    settings: Settings,
) -> SaleResolveHoldAlertNotifier:
    chat_id = settings.telegram.alert_chat_id
    bot_token = settings.telegram.bot_token.get_secret_value().strip()
    if chat_id is None or not bot_token:
        return NoOpSaleResolveHoldAlertNotifier()
    return TelegramSaleResolveHoldAlertNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        cooldown_minutes=settings.kitvending.sale_resolve_alert_cooldown_minutes,
    )


@beartype
@dataclass(frozen=True, slots=True)
class SettlementWiring:
    bundle: SettlementBundle
    moysklad_client: MoySkladClient | None
    machine_sales_store: object
    coffee_recipe_repo: CoffeeRecipeRepository
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository
    revision_history: EventStoreMachineRevisionHistoryReader
    close_responsibility_period: CloseResponsibilityPeriodOnRevision
    post_accountability: PostPeriodAccountability
    technician_settlement_repository: TechnicianSettlementRepository
    company_occupancy_store: MachineCompanyOccupancyStore
    kitshop_client: KitShopHttpClient | None = None
    micromarket_shop_list_gateway: KitShopMatrixGateway | None = None


@beartype
def wire_settlement(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
    event_store: EventStore,
    form_submission_store: FormSubmissionStore,
    vending_machines: VendingMachineRepository,
    domain_product_store: DomainProductStore,
    machine_sales_store: MachineSalesStore | None = None,
    snack_stock_store: SnackMachineStockStore | None = None,
    kit_matrix_deploy_map: KitMatrixDeployMapStore | None = None,
    occupancy_store: MachineCompanyOccupancyStore,
    after_occupancy_rebuild: Callable[[], None] | None = None,
    apply_micromarket_sale: ApplyMicromarketSaleToStock | None = None,
    reference_provider: ReferenceDataProvider | None = None,
    include_kit_shop_http: bool = True,
    include_moysklad_http: bool = True,
) -> SettlementWiring:
    resolved_sales_store = machine_sales_store or build_machine_sales_store(
        settings,
        client=mongo_client,
    )
    coffee_recipe_repo = build_coffee_recipe_repository(settings, client=mongo_client)
    reconciliation_repo = build_period_reconciliation_repository(settings, client=mongo_client)
    revision_history = EventStoreMachineRevisionHistoryReader(event_store=event_store)
    moysklad_client = build_moysklad_client(settings.moysklad) if include_moysklad_http else None
    party_names_lookup = VendingMachinePeriodPartyNamesLookup(machines=vending_machines)
    close_responsibility_period = CloseResponsibilityPeriodOnRevision(
        form_submission_store=form_submission_store,
        revision_history=revision_history,
        sales_store=resolved_sales_store,
        reconciliation_repo=reconciliation_repo,
        coffee_recipe_repo=coffee_recipe_repo,
        domain_product_store=domain_product_store,
        party_names_lookup=party_names_lookup,
        tolerance_seconds=settings.settlement.sales_coverage_tolerance_seconds,
    )
    technician_settlement_repository = build_technician_settlement_repository(
        settings,
        client=mongo_client,
    )
    settlement_executor = TechnicianSettlementExecutor(
        repository=technician_settlement_repository,
    )
    post_accountability = PostPeriodAccountability(
        settlement_executor=settlement_executor,
        reconciliation_repo=reconciliation_repo,
    )
    refresh_pending_with_accountability = build_refresh_pending_with_accountability(
        settings,
        mongo_client=mongo_client,
        domain_product_store=domain_product_store,
        reconciliation_repo=reconciliation_repo,
        sales_store=resolved_sales_store,
        coffee_recipe_repo=coffee_recipe_repo,
        form_submission_store=form_submission_store,
        revision_history=revision_history,
        post_accountability=post_accountability,
    )
    request_id_store = build_kitvending_request_id_store(
        settings,
        mongo_client=mongo_client,
    )
    skip_store = build_machine_sale_skip_store(settings, client=mongo_client)
    company_store = build_company_store(settings, mongo_client=mongo_client)
    kitvending_client = build_kitvending_client(
        settings.kitvending,
        request_id_store=request_id_store,
        skip_store=skip_store,
        company_store=company_store,
        domain_product_identity_enabled=settings.domain_product_identity.enabled,
        resolve_sale_code=(
            build_domain_product_resolver(
                settings,
                reference_provider,
                client=mongo_client,
            )
            if reference_provider is not None
            else None
        ),
    )
    import_sales = ImportKitVendingSales(
        sales_store=resolved_sales_store,
        kitvending_client=kitvending_client,
        apply_snack_sale=build_apply_snack_sale(
            settings,
            mongo_client=mongo_client,
            stock_store=snack_stock_store,
            deploy_map=kit_matrix_deploy_map,
        ),
        unresolved_alert_min=settings.snack_loading.sale_unresolved_alert_min,
        unresolved_alert_notifier=_build_unresolved_alert_notifier(settings),
        skip_store=skip_store,
        occupancy_store=occupancy_store,
        after_occupancy_rebuild=after_occupancy_rebuild,
    )
    kitvending = settings.kitvending
    kitvending.require_configured_for_ingestion()
    sales_ingest_worker: SalesIngestWorker | None = None
    if kitvending.ingestion_enabled:
        sales_ingest_worker = SalesIngestWorker(
            import_sales=import_sales,
            refresh_pending=refresh_pending_with_accountability,
            sales_store=resolved_sales_store,
            poll_interval_seconds=float(kitvending.poll_interval_seconds),
            initial_lookback=timedelta(days=kitvending.initial_lookback_days),
            reconciliation_repo=reconciliation_repo,
            tolerance_seconds=settings.settlement.sales_coverage_tolerance_seconds,
            resolve_hold_notifier=_build_sale_resolve_hold_notifier(settings),
            overlap_seconds=kitvending.sales_ingest_overlap_seconds,
        )
    else:
        _LOGGER.info("kitvending_sales_ingestion_disabled")

    kitshop = settings.kitshop
    kitshop.require_configured_for_ingestion()
    kitshop_client = (
        build_kitshop_client(
            kitshop,
            request_id_store=request_id_store,
        )
        if include_kit_shop_http
        else None
    )
    micromarket_shop_list_gateway: KitShopMatrixGateway | None = None
    resolved_kitshop_http: KitShopHttpClient | None = None
    if isinstance(kitshop_client, KitShopHttpClient):
        resolved_kitshop_http = kitshop_client
        micromarket_shop_list_gateway = KitShopMatrixGateway(
            api=kitshop_client.api,
            catalog_ensure_enabled=kitshop.catalog_ensure_on_publish_enabled,
        )

    kitshop_sales_ingest_worker: KitShopSalesIngestWorker | None = None
    if kitshop.ingestion_enabled and include_kit_shop_http:
        if mongo_client is None:
            raise ValueError(
                "KITSHOP_SALES_INGESTION_ENABLED=true требует MONGODB_URI (Mongo backlog/cursors)",
            )
        if apply_micromarket_sale is None:
            raise ValueError(
                "KITSHOP_SALES_INGESTION_ENABLED=true требует ApplyMicromarketSaleToStock",
            )
        if resolved_kitshop_http is None:
            raise ValueError(
                "KITSHOP_SALES_INGESTION_ENABLED=true, но Kit Shop client не сконфигурирован",
            )
        gateway = KitShopSalesGatewayAdapter(client=resolved_kitshop_http)
        backlog = MongoKitShopSalesBacklogStore.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
        cursor_store = MongoKitShopSalesIngestCursorStore.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
        company_directory = build_kit_company_directory(company_store)
        discover = DiscoverKitShopSales(
            gateway=gateway,
            backlog=backlog,
            cursor_store=cursor_store,
            overlap_seconds=kitshop.ingest_overlap_seconds,
            initial_lookback=timedelta(days=kitshop.initial_lookback_days),
        )
        receipts = MongoKitShopSaleReceiptStore.from_settings(
            settings.mongodb,
            client=mongo_client,
        )
        kitshop_alert_notifier = _build_kitshop_sale_alert_notifier(settings)
        drain = DrainKitShopSalesBacklog(
            gateway=gateway,
            backlog=backlog,
            sales_store=resolved_sales_store,
            apply_micromarket_sale=apply_micromarket_sale,
            company_resolver=KitShopCompanyIdResolverAdapter(directory=company_directory),
            receipts=receipts,
            unresolved_alert_min=settings.micromarket_loading.sale_unresolved_alert_min,
            unresolved_alert_notifier=kitshop_alert_notifier,
            domain_product_identity_enabled=settings.domain_product_identity.enabled,
            resolve_sale_code=(
                build_domain_product_kit_shop_resolver(
                    settings,
                    reference_provider,
                    client=mongo_client,
                )
                if reference_provider is not None
                else None
            ),
            occupancy_store=occupancy_store,
            after_occupancy_rebuild=after_occupancy_rebuild,
        )
        kitshop_sales_ingest_worker = KitShopSalesIngestWorker(
            discover=discover,
            drain=drain,
            refresh_pending=refresh_pending_with_accountability,
            discovery_interval_seconds=float(kitshop.discovery_interval_seconds),
            drain_interval_seconds=float(kitshop.drain_interval_seconds),
            reconciliation_repo=reconciliation_repo,
            sales_store=resolved_sales_store,
            tolerance_seconds=settings.settlement.sales_coverage_tolerance_seconds,
            alert_notifier=kitshop_alert_notifier,
        )
    else:
        _LOGGER.info("kitshop_sales_ingestion_disabled")

    kitshop_reference_snapshot_store = build_kitshop_reference_snapshot_store(
        settings,
        client=mongo_client,
    )
    kitshop_reference_snapshot_worker = None
    if resolved_kitshop_http is not None:
        resolved_kitshop_http.reference_snapshot_store = kitshop_reference_snapshot_store
        kitshop_reference_snapshot_worker = KitShopReferenceSnapshotWorker(
            store=kitshop_reference_snapshot_store,
            api=resolved_kitshop_http.api,
            refresh_interval_seconds=float(kitshop.reference_refresh_interval_seconds),
        )

    return SettlementWiring(
        bundle=SettlementBundle(
            sales_ingest_worker=sales_ingest_worker,
            kitshop_sales_ingest_worker=kitshop_sales_ingest_worker,
            kitvending_client=kitvending_client,
            company_occupancy_store=occupancy_store,
            kitshop_reference_snapshot_store=kitshop_reference_snapshot_store,
            kitshop_reference_snapshot_worker=kitshop_reference_snapshot_worker,
        ),
        moysklad_client=moysklad_client,
        machine_sales_store=resolved_sales_store,
        coffee_recipe_repo=coffee_recipe_repo,
        reconciliation_repo=reconciliation_repo,
        revision_history=revision_history,
        close_responsibility_period=close_responsibility_period,
        post_accountability=post_accountability,
        technician_settlement_repository=technician_settlement_repository,
        company_occupancy_store=occupancy_store,
        kitshop_client=resolved_kitshop_http,
        micromarket_shop_list_gateway=micromarket_shop_list_gateway,
    )
