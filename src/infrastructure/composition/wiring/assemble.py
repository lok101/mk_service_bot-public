from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any
from zoneinfo import ZoneInfo

from beartype import beartype
from pymongo import MongoClient

from src.application.master_data import MasterDataStores, run_master_data_sheets_export
from src.application.reference_data import ReferenceDataProvider
from src.application.sales_monitoring.no_sales_control import NoSalesVisitBlockLookup
from src.application.technician_accountability.executor import TechnicianAccountabilityExecutor
from src.application.technician_accountability.record_duplicate import (
    RecordPhotoDuplicateSuspectedService,
)
from src.config.settings import (
    Settings,
    get_settings,
    validate_machine_pnl_month_settings,
    validate_micromarket_supply_order_category_settings,
    validate_product_catalog_ms_settings,
    validate_product_procurement_mirror_settings,
)
from src.domain.ids import MachineId
from src.infrastructure.composition.adapters.auto_reconcile_accept_hook import (
    AcceptWithAutoReconcileEnqueue,
)
from src.infrastructure.composition.adapters.outbox_failure_notifier import (
    build_outbox_failure_notifier,
)
from src.infrastructure.composition.bundles.config import AppConfig
from src.infrastructure.composition.bundles.outbox import OutboxBundle
from src.infrastructure.composition.bundles.reference_data import ReferenceDataBundle
from src.infrastructure.composition.bundles.telegram import TelegramBundle
from src.infrastructure.composition.container import AppContainer
from src.infrastructure.composition.factories import (
    attach_master_data,
    attach_system_users,
    attach_technicians,
    build_apply_micromarket_sale_to_stock,
    build_border_registration_store,
    build_coffee_equipment_stores,
    build_company_store,
    build_daily_sales_demand_handler,
    build_domain_product_store,
    build_form_submission_store,
    build_kit_matrix_deploy_map_store,
    build_location_roster_draft_store,
    build_location_roster_store,
    build_machine_company_occupancy_store,
    build_machine_pnl_month_handler,
    build_machine_pnl_period_handler,
    build_machine_sales_store,
    build_master_data_export_hook,
    build_master_data_stores,
    build_micromarket_device_stock_store,
    build_micromarket_planogram_store,
    build_moysklad_client,
    build_outbox_store,
    build_photo_content_hash_index,
    build_photo_integrity_finding_store,
    build_procurement_mirror_worker,
    build_product_catalog_ms_worker,
    build_product_code_resolver,
    build_reference_data_snapshot_store,
    build_reference_data_sync,
    build_reference_data_worker,
    build_sales_monitoring_audit_store,
    build_service_visit_store,
    build_settlement_portion_handlers,
    build_shop_list_baseline_store,
    build_shop_list_publish_journal,
    build_snack_machine_stock_store,
    build_system_user_store,
    build_technician_accountability_repository,
    build_technician_store,
    grant_planogram_panel_if_mongo,
)
from src.infrastructure.composition.factories.company_directory import (
    build_company_display_names_map,
)
from src.infrastructure.composition.factories.current_company_names import (
    build_machine_company_names,
)
from src.infrastructure.composition.validation import validate_runtime_settings
from src.infrastructure.composition.wiring.deps import OutboxHandlerDeps
from src.infrastructure.composition.wiring.register_outbox_handlers import (
    OutboxProcess,
    register_outbox_handlers,
)
from src.infrastructure.composition.wiring.wire_forms import wire_forms
from src.infrastructure.composition.wiring.wire_machine_ops import wire_machine_ops
from src.infrastructure.composition.wiring.wire_persistence import wire_persistence
from src.infrastructure.composition.wiring.wire_photos import wire_photos
from src.infrastructure.composition.wiring.wire_settlement import wire_settlement
from src.infrastructure.composition.wiring.wire_technician_warehouse import (
    wire_technician_warehouse,
)
from src.infrastructure.composition.wiring.wire_worker_liveness import (
    wire_worker_liveness_watchdog,
)
from src.infrastructure.outbox import OutboxDomainEventPublisher, OutboxProcessorRegistry
from src.infrastructure.outbox.event_deserializer import OutboxEventDeserializerAdapter
from src.infrastructure.outbox.settlement_publisher import SettlementOutboxPublisher
from src.infrastructure.outbox.worker import OutboxWorker
from src.infrastructure.reference_data.coffee_recipe_drink_source import (
    CoffeeRecipeProductCatalogDrinkSource,
)
from src.infrastructure.reference_data.provider_sellable_catalog import (
    ProviderSellableProductCodeCatalog,
)
from src.interfaces.telegram.machines.deps import MachineDialogDeps


@beartype
def assemble_app_container(
    settings: Settings | None = None,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None | object = ...,
    process: OutboxProcess = "ingress",
) -> AppContainer:
    resolved = settings or get_settings()
    validate_runtime_settings(resolved)
    validate_product_catalog_ms_settings(resolved)
    validate_product_procurement_mirror_settings(resolved)
    validate_micromarket_supply_order_category_settings(resolved)
    google_forms = resolved.google_forms
    telegram_settings = resolved.telegram

    persistence = wire_persistence(resolved, mongo_client=mongo_client)
    outbox_store = build_outbox_store(resolved, client=persistence.mongo_client)
    processors = OutboxProcessorRegistry()
    publisher = OutboxDomainEventPublisher(store=outbox_store)
    settlement_publisher = SettlementOutboxPublisher(store=outbox_store)

    reference_provider = ReferenceDataProvider()
    reference_store = build_reference_data_snapshot_store(
        resolved,
        client=persistence.mongo_client,
    )
    roster_store = build_location_roster_store(resolved, client=persistence.mongo_client)
    roster_draft_store = build_location_roster_draft_store(
        resolved,
        client=persistence.mongo_client,
    )
    reference_provider.configure_roster(
        enabled=resolved.location_roster.enabled,
        store=roster_store if resolved.location_roster.enabled else None,
    )
    master_data_stores = build_master_data_stores(
        resolved,
        mongo_client=persistence.mongo_client,
    )
    coffee_equipment_stores = build_coffee_equipment_stores(
        resolved,
        mongo_client=persistence.mongo_client,
    )
    attach_master_data(
        reference_provider,
        stores=master_data_stores,
        enabled=resolved.master_data.enabled,
    )
    system_user_store = build_system_user_store(
        resolved,
        mongo_client=persistence.mongo_client,
    )
    grant_planogram_panel_if_mongo(system_user_store)
    attach_system_users(
        reference_provider,
        store=system_user_store,
        enabled=resolved.master_data.users_enabled,
    )
    technician_store = build_technician_store(
        resolved,
        mongo_client=persistence.mongo_client,
    )
    attach_technicians(
        reference_provider,
        store=technician_store,
        enabled=resolved.master_data.technicians_enabled,
    )
    reference_sync = build_reference_data_sync(
        resolved,
        store=reference_store,
        provider=reference_provider,
    )
    reference_worker = build_reference_data_worker(
        resolved,
        sync=reference_sync,
        store=reference_store,
    )

    product_code_resolver = build_product_code_resolver(reference_provider)
    include_moysklad_http = process == "effects"
    machine_ops = wire_machine_ops(
        resolved,
        mongo_client=persistence.mongo_client,
        publisher=publisher,
        provider=reference_provider,
        include_moysklad_http=include_moysklad_http,
    )
    form_submission_store = build_form_submission_store(
        resolved,
        client=persistence.mongo_client,
    )
    machine_sales_store = build_machine_sales_store(
        resolved,
        client=persistence.mongo_client,
    )
    snack_stock_store = build_snack_machine_stock_store(
        resolved,
        client=persistence.mongo_client,
    )
    kit_matrix_deploy_map = build_kit_matrix_deploy_map_store(
        resolved,
        client=persistence.mongo_client,
    )
    domain_product_store = build_domain_product_store(
        resolved.mongodb,
        resolved.domain_product_identity,
        client=persistence.mongo_client,
    )
    border_registration_store = build_border_registration_store(
        resolved.mongodb,
        resolved.domain_product_identity,
        client=persistence.mongo_client,
    )
    (
        procurement_mirror_worker,
        procurement_mirror_store,
        procurement_sync,
        procurement_mirror_http_close,
    ) = build_procurement_mirror_worker(
        resolved,
        domain_product_store=domain_product_store,
        mongo_client=persistence.mongo_client,
        include_moysklad_http=include_moysklad_http,
    )
    technician_warehouse = wire_technician_warehouse(
        resolved,
        mongo_client=persistence.mongo_client,
        form_submission_store=form_submission_store,
        product_code_resolver=product_code_resolver,
        provider=reference_provider,
        moysklad_client=(
            build_moysklad_client(resolved.moysklad) if include_moysklad_http else None
        ),
        publisher=publisher,
        domain_products=domain_product_store,
        border_registrations=border_registration_store,
    )
    shop_list_publish_journal = build_shop_list_publish_journal(
        resolved,
        client=persistence.mongo_client,
    )

    shop_list_baseline_store = build_shop_list_baseline_store(
        resolved,
        client=persistence.mongo_client,
    )

    forms = wire_forms(
        resolved,
        mongo_client=persistence.mongo_client,
        machine_ops=machine_ops,
        product_code_resolver=product_code_resolver,
        provider=reference_provider,
        technician_warehouse=technician_warehouse,
        form_submission_store=form_submission_store,
        machine_sales_store=machine_sales_store,
        snack_stock_store=snack_stock_store,
        kit_matrix_deploy_map=kit_matrix_deploy_map,
        publisher=publisher,
        domain_product_store=domain_product_store,
        shop_list_publish_journal=shop_list_publish_journal,
        shop_list_baseline_store=shop_list_baseline_store,
    )
    if resolved.settlement.auto_reconcile_enabled:
        accept_with_enqueue = AcceptWithAutoReconcileEnqueue(
            inner=technician_warehouse.accept_inventory,
            outbox_store=outbox_store,
            publisher=publisher,
            auto_reconcile_enabled=True,
            warehouse_repository=technician_warehouse.executor.repository,
        )
        forms = replace(
            forms,
            webhook_deps=replace(
                forms.webhook_deps,
                accept_technician_warehouse_inventory=accept_with_enqueue,
            ),
        )
    photos = wire_photos(
        resolved,
        mongo_client=persistence.mongo_client,
        machine_ops=machine_ops,
        machines=master_data_stores.machines,
    )
    occupancy_store = build_machine_company_occupancy_store(
        resolved,
        client=persistence.mongo_client,
    )
    after_occupancy_rebuild: Callable[[], None] | None = None
    if resolved.master_data.sheets_export_enabled and resolved.master_data.enabled:
        company_store = build_company_store(resolved, mongo_client=persistence.mongo_client)
        display_names = build_company_display_names_map(company_store)
        directory = reference_provider.technicians_directory_or_none()
        technician_names = dict(directory.names_by_id) if directory is not None else {}

        def _company_names_provider(stores: MasterDataStores) -> dict[MachineId, str]:
            return build_machine_company_names(
                occupancy_store=occupancy_store,
                display_names=display_names,
                machine_ids=tuple(m.machine_id for m in stores.machines.list_all()),
            )

        export_hook = build_master_data_export_hook(
            resolved,
            roster_store=roster_store,
            technician_names=technician_names,
            company_names_provider=_company_names_provider,
        )

        def after_occupancy_rebuild() -> None:
            run_master_data_sheets_export(export_hook, master_data_stores)

    apply_micromarket_sale_to_stock = build_apply_micromarket_sale_to_stock(
        resolved,
        machine_store=master_data_stores.machines,
        client=persistence.mongo_client,
    )
    settlement_wiring = wire_settlement(
        resolved,
        mongo_client=persistence.mongo_client,
        event_store=machine_ops.event_store,
        form_submission_store=forms.submission_store,
        vending_machines=machine_ops.vending_machines,
        domain_product_store=domain_product_store,
        machine_sales_store=machine_sales_store,
        snack_stock_store=snack_stock_store,
        kit_matrix_deploy_map=kit_matrix_deploy_map,
        occupancy_store=occupancy_store,
        after_occupancy_rebuild=after_occupancy_rebuild,
        apply_micromarket_sale=apply_micromarket_sale_to_stock,
        reference_provider=reference_provider,
        include_kit_shop_http=process == "effects",
        include_moysklad_http=include_moysklad_http,
    )
    machine_pnl_period_handler = build_machine_pnl_period_handler(
        resolved,
        reconciliation_repo=settlement_wiring.reconciliation_repo,
        machine_sales_store=settlement_wiring.machine_sales_store,
        settlement_repository=settlement_wiring.technician_settlement_repository,
        event_store=machine_ops.event_store,
        client=persistence.mongo_client,
    )
    if resolved.machine_pnl_month.enabled:
        validate_machine_pnl_month_settings(resolved)
    machine_pnl_month_handler = build_machine_pnl_month_handler(
        resolved,
        reconciliation_repo=settlement_wiring.reconciliation_repo,
        machine_sales_store=settlement_wiring.machine_sales_store,
        coffee_recipe_repo=settlement_wiring.coffee_recipe_repo,
        domain_product_store=domain_product_store,
        event_store=machine_ops.event_store,
        client=persistence.mongo_client,
    )
    daily_sales_demand_handler = build_daily_sales_demand_handler(
        resolved,
        machine_sales_store=settlement_wiring.machine_sales_store,
        moysklad_client=settlement_wiring.moysklad_client,
        sellable_catalog=ProviderSellableProductCodeCatalog(provider=reference_provider),
        client=persistence.mongo_client,
    )
    portion_handlers = build_settlement_portion_handlers(
        resolved,
        publisher=publisher,
        importer=technician_warehouse.importer,
        warehouse_executor=technician_warehouse.executor,
        reconciliation_repo=settlement_wiring.reconciliation_repo,
        settlement_repository=settlement_wiring.technician_settlement_repository,
        machine_sales_store=settlement_wiring.machine_sales_store,  # type: ignore[arg-type]
        coffee_recipe_repo=settlement_wiring.coffee_recipe_repo,
        domain_product_store=domain_product_store,
        form_submission_store=forms.submission_store,
        revision_history=settlement_wiring.revision_history,
        post_accountability=settlement_wiring.post_accountability,
        vending_machines=machine_ops.vending_machines,
        reference_provider=reference_provider,
        client=persistence.mongo_client,
    )
    product_catalog_ms_worker = build_product_catalog_ms_worker(
        product_catalog_ms=resolved.product_catalog_ms,
        moysklad_client=settlement_wiring.moysklad_client,
        store=reference_store,
        provider=reference_provider,
        drink_source=CoffeeRecipeProductCatalogDrinkSource(
            settlement_wiring.coffee_recipe_repo,
            domain_product_store,
        ),
    )
    reference_data = ReferenceDataBundle(
        provider=reference_provider,
        store=reference_store,
        roster_store=roster_store,
        roster_draft_store=roster_draft_store,
        master_data_stores=master_data_stores,
        system_user_store=system_user_store,
        technician_store=technician_store,
        sync=reference_sync,
        worker=reference_worker,
        product_catalog_ms_worker=product_catalog_ms_worker,
        coffee_equipment_stores=coffee_equipment_stores,
    )
    visit_store = build_service_visit_store(resolved, client=persistence.mongo_client)
    telegram = TelegramBundle(
        machine_dialog_deps=MachineDialogDeps(
            telegram_user_resolver=forms.telegram_user_resolver,
            technician_warehouse_inventory_link_provider=technician_warehouse.link_provider,
        ),
        visit_store=visit_store,
    )

    hash_index = build_photo_content_hash_index(resolved, client=persistence.mongo_client)
    finding_store = build_photo_integrity_finding_store(resolved, client=persistence.mongo_client)
    accountability_repository = build_technician_accountability_repository(
        resolved,
        client=persistence.mongo_client,
    )
    record_duplicate = RecordPhotoDuplicateSuspectedService(
        executor=TechnicianAccountabilityExecutor(
            repository=accountability_repository,
        ),
    )

    micromarket_planogram_store = build_micromarket_planogram_store(
        resolved,
        client=persistence.mongo_client,
    )
    micromarket_stock_store = build_micromarket_device_stock_store(
        resolved,
        client=persistence.mongo_client,
    )
    sales_monitoring_audit_store = build_sales_monitoring_audit_store(
        resolved,
        client=persistence.mongo_client,
    )
    audit_control: NoSalesVisitBlockLookup | None = (
        sales_monitoring_audit_store
        if isinstance(sales_monitoring_audit_store, NoSalesVisitBlockLookup)
        else None
    )
    from src.infrastructure.composition.factories.micromarket_loading import (
        build_micromarket_loading_move_command_store,
        build_moysklad_micromarket_move_client,
    )

    micromarket_loading_move_command_store = build_micromarket_loading_move_command_store(
        resolved,
        client=persistence.mongo_client,
    )
    micromarket_loading_move_client = build_moysklad_micromarket_move_client(
        resolved,
        settlement_wiring.moysklad_client,
    )
    from src.infrastructure.composition.wiring.post_visit_squeeze import (
        build_post_visit_squeeze,
    )

    post_visit_squeeze = build_post_visit_squeeze(
        resolved,
        mongo_client=persistence.mongo_client,
        cycle_store=machine_ops.micromarket_loading_cycle_store,
        stock_store=micromarket_stock_store,
        planogram_store=micromarket_planogram_store,
        sales_store=machine_sales_store,
        publisher=publisher,
        products=domain_product_store,
        journal=shop_list_publish_journal,
        baseline_store=shop_list_baseline_store,
        timezone=machine_ops.service_calendar_timezone,
        day_end_hour=resolved.service_calendar.service_day_end_hour,
    )

    register_outbox_handlers(
        publisher=publisher,
        processors=processors,
        process=process,
        deps=OutboxHandlerDeps(
            form_submission_store=forms.submission_store,
            observe_technician_warehouse_loading=technician_warehouse.observe_loading,
            photo_batch_store=photos.batch_store,
            photo_storage=photos.storage,
            photo_downloader_ref=photos.downloader_ref,
            loading_photos_notifier_ref=photos.loading_photos_notifier_ref,
            integrity_alert_notifier_ref=photos.integrity_alert_notifier_ref,
            hash_index=hash_index,
            finding_store=finding_store,
            record_duplicate=record_duplicate,
            vending_machine_repository=machine_ops.vending_machines,
            service_timezone=machine_ops.service_calendar_timezone,
            object_storage_key_prefix=resolved.object_storage.normalized_key_prefix(),
            photo_integrity_enabled=telegram_settings.photo_integrity_enabled,
            include_loading_photos_telegram=False,
            machine_sales_store=settlement_wiring.machine_sales_store,
            coffee_recipe_repo=settlement_wiring.coffee_recipe_repo,
            reconciliation_repo=settlement_wiring.reconciliation_repo,
            revision_history=settlement_wiring.revision_history,
            close_responsibility_period=settlement_wiring.close_responsibility_period,
            post_accountability=settlement_wiring.post_accountability,
            service_visit_store=visit_store,
            master_machine_store=(
                master_data_stores.machines if resolved.master_data.enabled else None
            ),
            service_day_end_hour=resolved.service_calendar.service_day_end_hour,
            no_sales_min_baseline_qty=resolved.service_visits.no_sales_min_baseline_qty,
            sales_baseline_timezone=ZoneInfo(resolved.sales_monitoring.tz),
            sales_baseline_days_for_average=resolved.sales_monitoring.days_for_average,
            sales_baseline_min_points=resolved.sales_monitoring.baseline_min_points,
            sales_baseline_winsorize_min_points=(
                resolved.sales_monitoring.baseline_winsorize_min_points
            ),
            sales_baseline_winsorize_percent=resolved.sales_monitoring.baseline_winsorize_percent,
            machine_pnl_period_handler=machine_pnl_period_handler,
            machine_pnl_month_handler=machine_pnl_month_handler,
            daily_sales_demand_handler=daily_sales_demand_handler,
            settlement_portion_sync_handler=(
                None if portion_handlers is None else portion_handlers.sync
            ),
            settlement_portion_sales_verify_handler=(
                None if portion_handlers is None else portion_handlers.sales_verify
            ),
            settlement_portion_reconcile_handler=(
                None if portion_handlers is None else portion_handlers.reconcile
            ),
            visit_photo_grouping_enabled=resolved.visit_photo_grouping.enabled,
            visit_photo_grouping_handler=None,
            micromarket_planogram_store=micromarket_planogram_store,
            micromarket_stock_store=micromarket_stock_store,
            shop_list_publish_journal=shop_list_publish_journal,
            shop_list_baseline_store=shop_list_baseline_store,
            micromarket_shop_list_gateway=settlement_wiring.micromarket_shop_list_gateway,
            domain_product_store=domain_product_store,
            sales_monitoring_audit_store=audit_control,
            telegram_user_resolver=forms.telegram_user_resolver,
            bot_token=resolved.telegram.bot_token.get_secret_value(),
            task_notify_enabled=resolved.service_visits.task_notify_enabled,
            task_notify_telegram_chat_id=resolved.service_visits.task_notify_telegram_chat_id,
            micromarket_loading_move_command_store=micromarket_loading_move_command_store,
            micromarket_loading_move_client=micromarket_loading_move_client,
            post_visit_squeeze=post_visit_squeeze,
        ),
    )

    outbox_worker = OutboxWorker(
        store=outbox_store,
        processors=processors,
        poll_interval_seconds=resolved.mongodb.outbox_poll_interval_seconds,
        failure_notifier=build_outbox_failure_notifier(
            resolved,
            form_submission_store=forms.submission_store,
            form_workflow_notifier=photos.form_workflow_notifier_ref.notifier,
            event_deserializer=OutboxEventDeserializerAdapter(),
            planogram_store=micromarket_planogram_store,
            shop_list_publish_journal=shop_list_publish_journal,
        ),
    )
    outbox = OutboxBundle(
        publisher=publisher,
        processors=processors,
        worker=outbox_worker,
        settlement_publisher=settlement_publisher,
    )
    config = AppConfig(
        bot_token=telegram_settings.bot_token.get_secret_value(),
        telegram_webhook_public_host=telegram_settings.webhook_public_host,
        telegram_webhook_path=telegram_settings.webhook_path,
        telegram_webhook_secret=telegram_settings.webhook_secret_value(),
        api_host=resolved.api_host,
        api_port=resolved.api_port,
        api_log_level=resolved.api_log_level,
        webhook_secret=google_forms.webhook_secret.get_secret_value(),
        webhook_signature_max_age_seconds=google_forms.webhook_signature_max_age_seconds,
        webhook_max_body_bytes=google_forms.webhook_max_body_bytes,
        revision_form_token_secret=google_forms.revision_form_token_secret.get_secret_value(),
        inventory_form_token_secret=google_forms.loading_form_token_secret.get_secret_value(),
        form_token_field_name=google_forms.token_field_name,
        form_token_ttl_hours=google_forms.form_token_ttl_hours,
    )
    worker_liveness = wire_worker_liveness_watchdog(
        resolved,
        mongo_client=persistence.mongo_client,
    )
    # LOK-160: ApplyMicromarketSaleToStock is built before wire_settlement and
    # injected into Kit Shop drain (ShopName → machine_code).
    return AppContainer(
        config=config,
        persistence=persistence,
        machine_ops=machine_ops,
        forms=forms,
        outbox=outbox,
        photos=photos,
        settlement=settlement_wiring.bundle,
        reference_data=reference_data,
        technician_warehouse=technician_warehouse,
        telegram=telegram,
        apply_micromarket_sale_to_stock=apply_micromarket_sale_to_stock,
        _moysklad_client=settlement_wiring.moysklad_client,
        kitshop_client=settlement_wiring.kitshop_client,
        micromarket_planogram_store=micromarket_planogram_store,
        shop_list_publish_journal=shop_list_publish_journal,
        shop_list_baseline_store=shop_list_baseline_store,
        procurement_mirror_worker=procurement_mirror_worker,
        procurement_mirror_store=procurement_mirror_store,
        procurement_sync=procurement_sync,
        worker_liveness_watchdog=worker_liveness,
        _procurement_mirror_http_close=procurement_mirror_http_close,
    )
