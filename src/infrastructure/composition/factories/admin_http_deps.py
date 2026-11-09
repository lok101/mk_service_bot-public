from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from beartype import beartype

from src.application.master_data import (
    CompanyStore,
    CreateCompany,
    CreateTechnician,
    MasterDataStores,
    SaveFieldStaff,
    SaveSystemUsers,
    UpdateCompany,
    UpdateTechnician,
)
from src.application.outbox.no_sales_incident_control import (
    enqueue_no_sales_incident_control as enqueue_no_sales_incident_control_impl,
)
from src.application.service_visits import BuildVisitBoardMonth
from src.application.technician_settlement import (
    AggregateSettlementClusters,
    BuildPeriodAnalysisView,
    BuildSessionAnalysisView,
    BuildSettlementAnalysisTree,
)
from src.application.visit_photo_review.profile import SaveVisitPhotoProfile
from src.config.settings import Settings
from src.domain.ids import MachineId
from src.domain.sales_monitoring.control_event import NoSalesIncidentControlAction
from src.infrastructure.composition.adapters.detach_visit_task_on_loading_rollback import (
    DetachVisitTaskOnLoadingRollbackAdapter,
)
from src.infrastructure.composition.adapters.ensure_open_visit_task import (
    EnsureOpenVisitTaskAdapter,
)
from src.infrastructure.composition.adapters.period_party_names import (
    VendingMachinePeriodPartyNamesLookup,
)
from src.infrastructure.composition.adapters.visit_board_lookups import (
    MasterLocationDisplayLookup,
    MasterPlacementAtLookup,
    RosterStoreEntriesLookup,
    TechniciansDirectoryDisplayLookup,
)
from src.infrastructure.composition.adapters.visit_photo_profile_lookup import (
    MasterCoffeeEquipmentCatalogLookup,
)
from src.infrastructure.composition.adapters.visit_photo_review_labels import (
    VendingMachineReviewLabelLookup,
)
from src.infrastructure.composition.factories import (
    build_admin_micromarket_loading_move_gateway,
    build_admin_nav_structure_store,
    build_border_registration_store,
    build_catalog_product_lookup,
    build_coffee_recipe_repository,
    build_domain_product_store,
    build_form_inventory_policy_store,
    build_maintenance_on_operational_day_lookup,
    build_master_data_export_hook,
    build_matrix_base_margin_store,
    build_matrix_sku_catalog_store,
    build_matrix_snapshot_store,
    build_micromarket_device_stock_store,
    build_micromarket_loading_move_command_store,
    build_micromarket_machine_multiplier_store,
    build_micromarket_planogram_store,
    build_micromarket_price_change_journal,
    build_micromarket_pricing_rules_store,
    build_micromarket_product_multiplier_store,
    build_micromarket_supply_order_store,
    build_micromarket_warehouse_stock_snapshot_store,
    build_period_reconciliation_repository,
    build_product_spec_by_code_resolver,
    build_sales_monitoring_audit_store,
    build_settlement_analysis_prefs_store,
    build_shop_list_baseline_store,
    build_shop_list_publish_journal,
    build_snack_machine_stock_store,
    build_supply_order_category_facts_snapshot_store,
    build_technician_settlement_repository,
)
from src.infrastructure.composition.factories.companies import build_company_store
from src.infrastructure.composition.factories.company_directory import (
    build_company_display_names_map,
)
from src.infrastructure.composition.factories.current_company_names import (
    build_machine_company_names,
)
from src.infrastructure.composition.factories.integrations import kit_shop_company_id
from src.infrastructure.composition.factories.visit_photo_review import (
    build_visit_photo_review_deps,
)
from src.infrastructure.composition.runtime import ProcessRuntime
from src.infrastructure.composition.wiring.sales_monitoring_worker_adapters import (
    SyncOutboxHandlerDrainer,
)
from src.infrastructure.integrations.kitshop.reference_snapshot import (
    KitShopReferenceSnapshotStore,
)
from src.infrastructure.mongodb.snack_machine_layouts import MongoSnackMachineLayoutStore
from src.infrastructure.mongodb.visit_photo_profiles import (
    build_mongo_visit_photo_profile_store,
)
from src.infrastructure.visit_photo_review.profile_storage import (
    FilesystemVisitPhotoProfileTechRefStorage,
)
from src.interfaces.admin.deps import AdminHttpDeps, KitProductGroupsLoad


def _load_kit_product_groups_unavailable() -> KitProductGroupsLoad:
    return KitProductGroupsLoad(error="Группы Kit Shop не загрузились", groups=())


_LOGGER = logging.getLogger(__name__)


@beartype
def build_snapshot_kit_product_groups_loader(
    *,
    store: KitShopReferenceSnapshotStore,
    kit_company_id: int,
    stale_after_seconds: float,
    clock: Callable[[], datetime] | None = None,
) -> Callable[[], KitProductGroupsLoad]:
    """Local snapshot groups for admin/Telegram; no Kit Shop HTTP."""

    def default_now() -> datetime:
        return datetime.now(tz=UTC)

    now_fn: Callable[[], datetime] = default_now if clock is None else clock

    def load_kit_product_groups() -> KitProductGroupsLoad:
        snapshot = store.get(kit_company_id)
        if snapshot is None:
            return KitProductGroupsLoad(
                error="Группы Kit Shop ещё не загружены",
                groups=(),
            )
        groups = tuple((group.group_id, group.group_name) for group in snapshot.groups)
        refreshed_at = snapshot.refreshed_at
        if refreshed_at.tzinfo is None:
            refreshed_at = refreshed_at.replace(tzinfo=UTC)
        else:
            refreshed_at = refreshed_at.astimezone(UTC)
        age_seconds = (now_fn() - refreshed_at).total_seconds()
        warning = ""
        if age_seconds > stale_after_seconds:
            warning = "Справочник полок устарел; показана последняя копия."
            _LOGGER.info(
                "kitshop_reference_snapshot_stale_read",
                extra={
                    "consumer": "admin_kit_product_groups",
                    "kit_company_id": kit_company_id,
                    "age_seconds": round(age_seconds, 1),
                },
            )
        return KitProductGroupsLoad(error="", groups=groups, warning=warning)

    return load_kit_product_groups


def _build_load_kit_product_groups(
    runtime: ProcessRuntime,
    *,
    reference_refresh_interval_seconds: int,
    kit_company_id: int | None,
) -> Callable[[], KitProductGroupsLoad]:
    store = runtime.settlement.kitshop_reference_snapshot_store
    if store is None or kit_company_id is None:
        return _load_kit_product_groups_unavailable

    return build_snapshot_kit_product_groups_loader(
        store=store,
        kit_company_id=kit_company_id,
        stale_after_seconds=float(reference_refresh_interval_seconds) * 2.0,
    )


@beartype
def build_admin_http_deps(runtime: ProcessRuntime, settings: Settings) -> AdminHttpDeps:
    roster = settings.location_roster
    master = settings.master_data
    auth = roster if roster.enabled else master
    secret = ""
    if auth.session_secret is not None:
        secret = auth.session_secret.get_secret_value()
    master_stores = None
    coffee_machine_model_store = None
    stand_type_store = None
    stand_color_store = None
    master_data_export_hook = None
    company_occupancy_store = None
    company_display_names: dict[int, str] | None = None
    company_store_admin: CompanyStore | None = None
    create_company = None
    update_company = None
    refresh_company_display_names = None
    if master.enabled or master.companies_enabled:
        company_store = build_company_store(
            settings,
            mongo_client=runtime.persistence.mongo_client,
        )
        company_store_admin = company_store
        if master.enabled:
            master_stores = runtime.reference_data.master_data_stores
            equipment = runtime.reference_data.coffee_equipment_stores
            if equipment is not None:
                coffee_machine_model_store = equipment.models
                stand_type_store = equipment.stand_types
                stand_color_store = equipment.stand_colors
            directory = runtime.reference_data.provider.technicians_directory_or_none()
            technician_names = dict(directory.names_by_id) if directory is not None else {}
            company_occupancy_store = runtime.settlement.company_occupancy_store
            # Display names from MasterCompany directory (see kit-companies spec step 6).
            company_display_names = build_company_display_names_map(company_store)
            occupancy = company_occupancy_store
            display_names = company_display_names

            def _company_names_provider(stores: MasterDataStores) -> dict[MachineId, str]:
                ids = tuple(m.machine_id for m in stores.machines.list_all())
                return build_machine_company_names(
                    occupancy_store=occupancy,
                    display_names=display_names,
                    machine_ids=ids,
                )

            master_data_export_hook = build_master_data_export_hook(
                settings,
                roster_store=runtime.reference_data.roster_store,
                technician_names=technician_names,
                company_names_provider=_company_names_provider,
            )
        else:
            company_display_names = build_company_display_names_map(company_store)
    if master.companies_enabled and company_store_admin is not None:
        md = runtime.reference_data.master_data_stores
        create_company = CreateCompany(
            store=company_store_admin,
            counters=md.counters,
            audit=md.audit,
        )
        update_company = UpdateCompany(
            store=company_store_admin,
            audit=md.audit,
        )
        names = company_display_names
        store_for_refresh = company_store_admin
        if names is not None:

            def _refresh_company_display_names() -> None:
                names.clear()
                names.update(build_company_display_names_map(store_for_refresh))

            refresh_company_display_names = _refresh_company_display_names
    build_visit_board = None
    domain_product_store = None
    form_inventory_policy_store = None
    coffee_recipe_repo = None
    refresh_pending_after_bom: Callable[[], None] | None = None
    catalog_product_lookup = None
    border_registration_store = None
    if master_stores is not None:
        domain_product_store = build_domain_product_store(
            settings.mongodb,
            settings.domain_product_identity,
            client=runtime.persistence.mongo_client,
        )
        form_inventory_policy_store = build_form_inventory_policy_store(
            settings.mongodb,
            client=runtime.persistence.mongo_client,
        )
        coffee_recipe_repo = build_coffee_recipe_repository(
            settings,
            client=runtime.persistence.mongo_client,
        )
        from src.infrastructure.composition.factories.settlement import (
            build_refresh_pending_with_accountability,
        )

        _bom_refresh = build_refresh_pending_with_accountability(
            settings,
            mongo_client=runtime.persistence.mongo_client,
            domain_product_store=domain_product_store,
            coffee_recipe_repo=coffee_recipe_repo,
        )

        def refresh_pending_after_bom() -> None:
            _bom_refresh.execute()

        catalog_product_lookup = build_catalog_product_lookup(runtime.reference_data.provider)
        border_registration_store = build_border_registration_store(
            settings.mongodb,
            settings.domain_product_identity,
            client=runtime.persistence.mongo_client,
        )
        build_visit_board = BuildVisitBoardMonth(
            visit_store=runtime.telegram.visit_store,
            roster=RosterStoreEntriesLookup(runtime.reference_data.roster_store),
            placements=MasterPlacementAtLookup(master_stores.placements),
            locations=MasterLocationDisplayLookup(master_stores.locations),
            technicians=TechniciansDirectoryDisplayLookup(runtime.reference_data.provider),
            timezone=settings.service_calendar.zone_info(),
            day_end_hour=settings.service_calendar.service_day_end_hour,
        )
    system_user_store = None
    save_system_users = None
    if master.users_enabled:
        system_user_store = runtime.reference_data.system_user_store
        save_system_users = SaveSystemUsers(
            store=system_user_store,
            counters=runtime.reference_data.master_data_stores.counters,
        )
    technician_store = None
    create_technician = None
    update_technician = None
    if master.technicians_enabled:
        technician_store = runtime.reference_data.technician_store
        create_technician = CreateTechnician(
            store=technician_store,
            counters=runtime.reference_data.master_data_stores.counters,
            audit=runtime.reference_data.master_data_stores.audit,
            export_hook=None,
        )
        update_technician = UpdateTechnician(
            store=technician_store,
            audit=runtime.reference_data.master_data_stores.audit,
            export_hook=None,
        )
    save_field_staff = None
    if master.users_enabled and save_system_users is not None:
        save_field_staff = SaveFieldStaff(
            save_system_users=save_system_users,
            create_technician=create_technician,
            update_technician=update_technician,
            technician_store=technician_store,
            technicians_enabled=master.technicians_enabled,
        )
    layout_master_enabled = settings.matrix_automation.layout_master_enabled
    snack_layout_store = None
    matrix_price_snapshot_store = None
    purchase_attributes_reader = None
    snack_stock_store = None
    if layout_master_enabled:
        snack_layout_store = MongoSnackMachineLayoutStore.from_settings(
            settings.mongodb,
            client=runtime.persistence.mongo_client,
        )
        matrix_price_snapshot_store = build_matrix_snapshot_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
        from src.infrastructure.composition.wiring.wire_matrix_worker import (
            build_purchase_attributes_reader,
        )

        purchase_attributes_reader, _ = build_purchase_attributes_reader(settings)
        snack_stock_store = build_snack_machine_stock_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
    sku_catalog_master_enabled = settings.matrix_automation.sku_catalog_master_enabled
    matrix_sku_catalog_store = (
        build_matrix_sku_catalog_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
        if sku_catalog_master_enabled
        else None
    )
    matrix_base_margin_store = build_matrix_base_margin_store(
        settings,
        client=runtime.persistence.mongo_client,
    )
    apply_snack_matrix = None
    if (
        layout_master_enabled
        and snack_layout_store is not None
        and matrix_price_snapshot_store is not None
        and purchase_attributes_reader is not None
        and runtime.persistence.mongo_client is not None
    ):
        from src.infrastructure.composition.matrix_automation_factory import (
            build_matrix_reference_data_provider,
        )
        from src.infrastructure.composition.wiring.wire_matrix_worker import (
            build_admin_apply_snack_matrix,
        )

        matrix_provider = build_matrix_reference_data_provider(settings.matrix_automation)
        apply_snack_matrix = build_admin_apply_snack_matrix(
            settings,
            snack_layout_store=snack_layout_store,
            snapshot_store=matrix_price_snapshot_store,
            purchase_reader=purchase_attributes_reader,
            base_margin_store=matrix_base_margin_store,
            provider=matrix_provider,
            client=runtime.persistence.mongo_client,
        )
    snack_sku_assortment_reader = None
    snack_sku_folder_ids: tuple[UUID, ...] = ()
    if sku_catalog_master_enabled:
        # ADR-0083: snack SKU assortment Remap is effects-owned; admin degrades without client.
        snack_sku_folder_ids = settings.matrix_automation.sku_catalog_ms_product_folder_ids
    settlement_analysis_enabled = settings.settlement_analysis.enabled
    build_settlement_analysis_tree = None
    aggregate_settlement_clusters = None
    build_session_analysis_view = None
    build_period_analysis_view = None
    settlement_analysis_prefs_store = None
    if settlement_analysis_enabled:
        settlement_repo = build_technician_settlement_repository(
            settings,
            client=runtime.persistence.mongo_client,
        )
        period_snapshots = build_period_reconciliation_repository(
            settings,
            client=runtime.persistence.mongo_client,
        )
        event_store = settlement_repo.event_store
        prefs_store = build_settlement_analysis_prefs_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
        party_names = VendingMachinePeriodPartyNamesLookup(
            machines=runtime.machine_ops.vending_machines,
        )
        catalog = build_product_spec_by_code_resolver(runtime.reference_data.provider)
        build_settlement_analysis_tree = BuildSettlementAnalysisTree(
            event_store=event_store,
            period_repository=period_snapshots,
            party_names_lookup=party_names,
        )
        aggregate_settlement_clusters = AggregateSettlementClusters(
            event_store=event_store,
            period_repository=period_snapshots,
            catalog=catalog,
        )
        build_session_analysis_view = BuildSessionAnalysisView(
            event_store=event_store,
            catalog=catalog,
        )
        build_period_analysis_view = BuildPeriodAnalysisView(
            period_repository=period_snapshots,
            party_names_lookup=party_names,
            catalog=catalog,
        )
        settlement_analysis_prefs_store = prefs_store
    admin_nav_structure_store = build_admin_nav_structure_store(
        settings,
        client=runtime.persistence.mongo_client,
    )
    micromarket_planogram_store = None
    micromarket_pricing_rules_store = None
    micromarket_product_multiplier_store = None
    micromarket_machine_multiplier_store = None
    micromarket_price_change_journal = None
    micromarket_stock_store = None
    shop_list_publish_journal = None
    shop_list_baseline_store = None
    micromarket_supply_order_store = None
    supply_order_category_facts = None
    supply_order_demand_forecast = None
    supply_order_snacks_folder_id = ""
    supply_order_ready_meals_folder_id = ""
    supply_order_shelf_life_days_threshold = 7
    micromarket_ms_product_folder_ids: tuple[UUID, ...] = ()
    micromarket_assortment_reader = None
    micromarket_loading_move_gateway = None
    micromarket_warehouse_stock_snapshot = build_micromarket_warehouse_stock_snapshot_store(
        settings,
        client=runtime.persistence.mongo_client,
    )
    if master_stores is not None:
        micromarket_planogram_store = runtime.micromarket_planogram_store
        if micromarket_planogram_store is None:
            micromarket_planogram_store = build_micromarket_planogram_store(
                settings,
                client=runtime.persistence.mongo_client,
            )
        micromarket_pricing_rules_store = build_micromarket_pricing_rules_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
        micromarket_product_multiplier_store = build_micromarket_product_multiplier_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
        micromarket_machine_multiplier_store = build_micromarket_machine_multiplier_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
        micromarket_price_change_journal = build_micromarket_price_change_journal(
            settings,
            client=runtime.persistence.mongo_client,
        )
        micromarket_stock_store = build_micromarket_device_stock_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
        shop_list_publish_journal = runtime.shop_list_publish_journal
        shop_list_baseline_store = runtime.shop_list_baseline_store
        if shop_list_publish_journal is None:
            shop_list_publish_journal = build_shop_list_publish_journal(
                settings,
                client=runtime.persistence.mongo_client,
            )
        if shop_list_baseline_store is None:
            shop_list_baseline_store = build_shop_list_baseline_store(
                settings,
                client=runtime.persistence.mongo_client,
            )
        micromarket_supply_order_store = build_micromarket_supply_order_store(
            settings,
            client=runtime.persistence.mongo_client,
        )
        from src.application.demand_analytics import (
            LONG_SHELF_TO_LIMIT_V1,
            SHORT_SHELF_LEAD_TIME_V1,
            DemandForecastEngine,
            LongShelfToLimitV1Policy,
            ShortShelfLeadTimeV1Policy,
        )
        from src.infrastructure.composition.factories.settlement import (
            build_machine_sales_store,
        )
        from src.infrastructure.demand_analytics.machine_sales_history import (
            MachineSalesHistory,
        )
        from src.infrastructure.demand_analytics.supply_order_forecast import (
            MicromarketDemandForecastAdapter,
        )
        from src.infrastructure.demand_analytics.virtual_stock_history import (
            VirtualStockHistory,
        )

        sales_history = MachineSalesHistory(
            build_machine_sales_store(
                settings,
                client=runtime.persistence.mongo_client,
            ),
        )
        virtual_stock = VirtualStockHistory(micromarket_stock_store)
        short_shelf_policy = ShortShelfLeadTimeV1Policy(virtual_stock=virtual_stock)
        long_shelf_policy = LongShelfToLimitV1Policy(virtual_stock=virtual_stock)
        supply_order_demand_forecast = MicromarketDemandForecastAdapter(
            engine=DemandForecastEngine(
                policies={
                    SHORT_SHELF_LEAD_TIME_V1: short_shelf_policy,
                    LONG_SHELF_TO_LIMIT_V1: long_shelf_policy,
                },
                history=sales_history,
            ),
            timezone=settings.service_calendar.zone_info(),
        )
        cat_settings = settings.micromarket_supply_order_category
        supply_order_snacks_folder_id = str(cat_settings.folder_snacks_id)
        supply_order_ready_meals_folder_id = str(cat_settings.folder_ready_meals_id)
        supply_order_shelf_life_days_threshold = cat_settings.shelf_life_days_threshold
        # ADR-0083: no live Remap in app — category facts from Mongo snapshot.
        from datetime import UTC, datetime

        from src.application.micromarket_loading.supply_order_category_facts_from_snapshot import (
            SupplyOrderCategoryFactsFromSnapshot,
        )

        supply_order_category_facts = SupplyOrderCategoryFactsFromSnapshot(
            store=build_supply_order_category_facts_snapshot_store(
                settings,
                client=runtime.persistence.mongo_client,
            ),
            now=lambda: datetime.now(tz=UTC),
            staleness_seconds=cat_settings.staleness_seconds,
        )
        micromarket_ms_product_folder_ids = settings.micromarket_loading.ms_product_folder_ids
        micromarket_loading_move_gateway = build_admin_micromarket_loading_move_gateway(
            settings,
            publisher=runtime.outbox.publisher,
            warehouse_stock=micromarket_warehouse_stock_snapshot,
            move_command_store=build_micromarket_loading_move_command_store(
                settings,
                client=runtime.persistence.mongo_client,
            ),
        )
    visit_photo_review_enabled = False
    review_queries = None
    save_review_record = None
    clear_review_record = None
    dispose_unrecognized_index = None
    group_avatar_reader = None
    update_group_defects = None
    write_group_avatar = None
    photo_storage = None
    review_label_lookup = None
    visit_photo_profile_store = None
    save_visit_photo_profile = None
    visit_photo_profile_tech_ref_storage = None
    if settings.visit_photo_review.enabled:
        visit_deps = build_visit_photo_review_deps(
            settings,
            client=runtime.persistence.mongo_client,
            photo_batch_store=runtime.photos.batch_store,
        )
        if visit_deps is not None:
            visit_photo_review_enabled = True
            review_queries = visit_deps.review_queries
            save_review_record = visit_deps.save_review_record
            clear_review_record = visit_deps.clear_review_record
            dispose_unrecognized_index = visit_deps.dispose_unrecognized_index
            group_avatar_reader = visit_deps.group_avatar_reader
            update_group_defects = visit_deps.update_group_defects
            write_group_avatar = visit_deps.write_group_avatar
            photo_storage = runtime.photos.storage
            review_label_lookup = VendingMachineReviewLabelLookup(
                machines=runtime.machine_ops.vending_machines,
            )
            if (
                settings.mongodb.is_configured
                and coffee_machine_model_store is not None
                and stand_type_store is not None
            ):
                visit_photo_profile_store = build_mongo_visit_photo_profile_store(
                    settings.mongodb,
                    settings.visit_photo_review,
                    client=runtime.persistence.mongo_client,
                )
                packs_root = settings.visit_photo_grouping.resolved_packs_root()
                reference_layout = None
                if packs_root is not None:
                    from src.infrastructure.visit_photo_review.profile_pack_io import (
                        FilesystemProfileGroupReferenceLayout,
                    )

                    reference_layout = FilesystemProfileGroupReferenceLayout(
                        packs_root=packs_root,
                    )
                save_visit_photo_profile = SaveVisitPhotoProfile(
                    store=visit_photo_profile_store,
                    catalog=MasterCoffeeEquipmentCatalogLookup(
                        models=coffee_machine_model_store,
                        stand_types=stand_type_store,
                    ),
                    reference_layout=reference_layout,
                )
                if packs_root is not None:
                    visit_photo_profile_tech_ref_storage = (
                        FilesystemVisitPhotoProfileTechRefStorage(
                            packs_root / "_technician_references",
                        )
                    )
    catalog_holder = runtime.reference_data.product_catalog_ms_worker
    product_catalog_sync = None if catalog_holder is None else catalog_holder.sync.sync_once
    micromarket_shop_list_publisher = None
    if kit_shop_company_id(settings.kitshop) is not None:
        micromarket_shop_list_publisher = runtime.outbox.publisher
    sales_monitoring_audit_store = build_sales_monitoring_audit_store(
        settings,
        client=runtime.persistence.mongo_client,
    )
    list_open_no_sales = getattr(sales_monitoring_audit_store, "list_open_no_sales", None)
    list_open_offline = getattr(sales_monitoring_audit_store, "list_open_offline", None)
    list_no_sales_controls = getattr(sales_monitoring_audit_store, "list_no_sales_controls", None)
    list_cleared_no_sales_since = getattr(
        sales_monitoring_audit_store,
        "list_cleared_no_sales_since",
        None,
    )
    list_no_sales_episodes_overlapping = getattr(
        sales_monitoring_audit_store,
        "list_no_sales_episodes_overlapping",
        None,
    )
    list_maintenance_completed_in_completed_at_window = getattr(
        runtime.machine_ops.event_store,
        "list_maintenance_completed_in_completed_at_window",
        None,
    )
    enqueue_no_sales_incident_control = None
    if callable(list_open_no_sales):
        publisher = runtime.outbox.publisher
        drainer = SyncOutboxHandlerDrainer(worker=runtime.outbox.worker)

        def enqueue_no_sales_incident_control(
            *,
            machine_id: MachineId,
            opened_event_id: str,
            action: NoSalesIncidentControlAction,
        ) -> None:
            enqueue_no_sales_incident_control_impl(
                publisher=publisher,
                drainer=drainer,
                machine_id=machine_id,
                opened_event_id=opened_event_id,
                action=action,
            )

    return AdminHttpDeps(
        provider=runtime.reference_data.provider,
        roster_store=runtime.reference_data.roster_store,
        roster_draft_store=runtime.reference_data.roster_draft_store,
        visit_store=runtime.telegram.visit_store,
        maintenance_lookup=build_maintenance_on_operational_day_lookup(
            runtime.machine_ops.event_store,
        ),
        bot_token=settings.telegram.bot_token.get_secret_value(),
        session_secret=secret,
        session_ttl_seconds=roster.session_ttl_seconds,
        telegram_auth_max_age_seconds=roster.telegram_auth_max_age_seconds,
        telegram_bot_username=auth.telegram_bot_username,
        stub_login_enabled=auth.dev_stub_login_enabled,
        timezone=settings.service_calendar.zone_info(),
        day_end_hour=settings.service_calendar.service_day_end_hour,
        now_factory=lambda: datetime.now(UTC),
        admin_max_body_bytes=settings.http_limits.admin_max_body_bytes,
        master_stores=master_stores,
        coffee_machine_model_store=coffee_machine_model_store,
        stand_type_store=stand_type_store,
        stand_color_store=stand_color_store,
        master_data_export_hook=master_data_export_hook,
        build_visit_board=build_visit_board,
        users_enabled=master.users_enabled,
        system_user_store=system_user_store,
        save_system_users=save_system_users,
        save_field_staff=save_field_staff,
        technicians_enabled=master.technicians_enabled,
        technician_store=technician_store,
        create_technician=create_technician,
        update_technician=update_technician,
        companies_enabled=master.companies_enabled,
        company_store=company_store_admin if master.companies_enabled else None,
        create_company=create_company,
        update_company=update_company,
        refresh_company_display_names=refresh_company_display_names,
        layout_master_enabled=layout_master_enabled,
        snack_layout_store=snack_layout_store,
        matrix_price_snapshot_store=matrix_price_snapshot_store,
        purchase_attributes_reader=purchase_attributes_reader,
        snack_stock_store=snack_stock_store,
        matrix_multiplier_min=settings.matrix_automation.matrix_multiplier_min,
        matrix_multiplier_max=settings.matrix_automation.matrix_multiplier_max,
        sku_catalog_master_enabled=sku_catalog_master_enabled,
        matrix_sku_catalog_store=matrix_sku_catalog_store,
        matrix_base_margin_store=matrix_base_margin_store,
        apply_snack_matrix=apply_snack_matrix,
        scale_price_min_bound=settings.matrix_automation.scale_price_min,
        scale_price_max_bound=settings.matrix_automation.scale_price_max,
        scale_rate_min_bound=settings.matrix_automation.scale_rate_min,
        scale_rate_max_bound=settings.matrix_automation.scale_rate_max,
        curvature_min=settings.matrix_automation.curvature_min,
        curvature_max=settings.matrix_automation.curvature_max,
        margin_floor_min=settings.matrix_automation.margin_floor_min,
        margin_floor_max=settings.matrix_automation.margin_floor_max,
        snack_sku_assortment_reader=snack_sku_assortment_reader,
        snack_sku_folder_ids=snack_sku_folder_ids,
        settlement_analysis_enabled=settlement_analysis_enabled,
        build_settlement_analysis_tree=build_settlement_analysis_tree,
        aggregate_settlement_clusters=aggregate_settlement_clusters,
        build_session_analysis_view=build_session_analysis_view,
        build_period_analysis_view=build_period_analysis_view,
        settlement_analysis_prefs_store=settlement_analysis_prefs_store,
        visit_photo_review_enabled=visit_photo_review_enabled,
        review_queries=review_queries,
        save_review_record=save_review_record,
        clear_review_record=clear_review_record,
        dispose_unrecognized_index=dispose_unrecognized_index,
        review_label_lookup=review_label_lookup,
        group_avatar_reader=group_avatar_reader,
        update_group_defects=update_group_defects,
        write_group_avatar=write_group_avatar,
        photo_storage=photo_storage,
        visit_photo_profile_store=visit_photo_profile_store,
        save_visit_photo_profile=save_visit_photo_profile,
        visit_photo_profile_tech_ref_storage=visit_photo_profile_tech_ref_storage,
        admin_nav_structure_store=admin_nav_structure_store,
        company_occupancy_store=company_occupancy_store,
        company_display_names=company_display_names,
        micromarket_planogram_store=micromarket_planogram_store,
        micromarket_pricing_rules_store=micromarket_pricing_rules_store,
        micromarket_product_multiplier_store=micromarket_product_multiplier_store,
        micromarket_machine_multiplier_store=micromarket_machine_multiplier_store,
        micromarket_price_change_journal=micromarket_price_change_journal,
        micromarket_margin_percent_min=settings.micromarket_pricing.margin_percent_min,
        micromarket_margin_percent_max=settings.micromarket_pricing.margin_percent_max,
        micromarket_margin_floor_min=settings.micromarket_pricing.margin_floor_min,
        micromarket_margin_floor_max=settings.micromarket_pricing.margin_floor_max,
        micromarket_product_multiplier_min=settings.micromarket_pricing.product_multiplier_min,
        micromarket_product_multiplier_max=settings.micromarket_pricing.product_multiplier_max,
        micromarket_machine_multiplier_min=settings.micromarket_pricing.machine_multiplier_min,
        micromarket_machine_multiplier_max=settings.micromarket_pricing.machine_multiplier_max,
        micromarket_max_price_delta_pct=settings.micromarket_pricing.max_price_delta_pct,
        micromarket_stock_store=micromarket_stock_store,
        shop_list_publish_journal=shop_list_publish_journal,
        shop_list_baseline_store=shop_list_baseline_store,
        micromarket_ms_product_folder_ids=micromarket_ms_product_folder_ids,
        micromarket_assortment_reader=micromarket_assortment_reader,
        micromarket_loading_cycle_store=runtime.machine_ops.micromarket_loading_cycle_store,
        micromarket_assembly_order_store=runtime.machine_ops.micromarket_assembly_order_store,
        micromarket_supply_order_store=micromarket_supply_order_store,
        supply_order_category_facts=supply_order_category_facts,
        supply_order_demand_forecast=supply_order_demand_forecast,
        supply_order_snacks_folder_id=supply_order_snacks_folder_id,
        supply_order_ready_meals_folder_id=supply_order_ready_meals_folder_id,
        supply_order_shelf_life_days_threshold=supply_order_shelf_life_days_threshold,
        micromarket_loading_execute_enabled=settings.micromarket_loading.execute_enabled,
        micromarket_loading_warehouse_gate_enabled=(
            settings.micromarket_loading.warehouse_gate_enabled
        ),
        micromarket_loading_move_gateway=micromarket_loading_move_gateway,
        micromarket_warehouse_stock_snapshot=micromarket_warehouse_stock_snapshot,
        micromarket_warehouse_stock_cold_wait_seconds=(
            settings.micromarket_loading.warehouse_stock_cold_wait_seconds
        ),
        ensure_open_visit_task=EnsureOpenVisitTaskAdapter(
            store=runtime.telegram.visit_store,
            timezone=settings.service_calendar.zone_info(),
            day_end_hour=settings.service_calendar.service_day_end_hour,
        ),
        detach_visit_on_loading_rollback=DetachVisitTaskOnLoadingRollbackAdapter(
            store=runtime.telegram.visit_store,
        ),
        load_kit_product_groups=_build_load_kit_product_groups(
            runtime,
            reference_refresh_interval_seconds=(
                settings.kitshop.reference_refresh_interval_seconds
            ),
            kit_company_id=kit_shop_company_id(settings.kitshop),
        ),
        micromarket_shop_list_publisher=micromarket_shop_list_publisher,
        domain_product_store=domain_product_store,
        form_inventory_policy_store=form_inventory_policy_store,
        coffee_recipe_repo=coffee_recipe_repo,
        refresh_pending_after_bom=refresh_pending_after_bom,
        border_registration_store=border_registration_store,
        catalog_product_lookup=catalog_product_lookup,
        catalog_snapshot_store=runtime.reference_data.store,
        product_catalog_sync=product_catalog_sync,
        procurement_mirror_enabled=settings.product_procurement_mirror.enabled,
        procurement_mirror_store=runtime.procurement_mirror_store,
        procurement_sync=runtime.procurement_sync,
        list_open_no_sales=list_open_no_sales if callable(list_open_no_sales) else None,
        list_open_offline=list_open_offline if callable(list_open_offline) else None,
        list_no_sales_controls=(
            list_no_sales_controls if callable(list_no_sales_controls) else None
        ),
        list_cleared_no_sales_since=(
            list_cleared_no_sales_since if callable(list_cleared_no_sales_since) else None
        ),
        list_no_sales_episodes_overlapping=(
            list_no_sales_episodes_overlapping
            if callable(list_no_sales_episodes_overlapping)
            else None
        ),
        list_maintenance_completed_in_completed_at_window=(
            list_maintenance_completed_in_completed_at_window
            if callable(list_maintenance_completed_in_completed_at_window)
            else None
        ),
        incident_clear_pair_minutes=settings.sales_monitoring.incident_clear_pair_minutes,
        enqueue_no_sales_incident_control=enqueue_no_sales_incident_control,
    )
