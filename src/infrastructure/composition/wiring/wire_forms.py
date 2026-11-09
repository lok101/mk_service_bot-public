from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.form_submissions.accept import (
    AcceptInventoryFormSubmissionService,
    AcceptRevisionFormSubmissionService,
)
from src.application.form_submissions.ports import FormSubmissionStore, ProductCodeResolver
from src.application.form_workflow.notifier_ref import FormWorkflowNotifierRef
from src.application.inventory_reconciliation.ports import MachineSalesStore
from src.application.machine_operations.services import (
    RegisterLoadingFromFormService,
    RegisterRevisionFromFormService,
)
from src.application.micromarket_loading import AcceptMicromarketInventory
from src.application.micromarket_loading.enqueue_post_visit_squeeze import (
    InMemoryEnqueuePostVisitSqueeze,
    OutboxEnqueuePostVisitSqueeze,
)
from src.application.micromarket_loading.ports import (
    CompleteOpenVisitTaskPort,
    EnqueuePostVisitSqueezePort,
    EnsureOpenVisitTaskPort,
    MicromarketDeviceStockStore,
    MicromarketPlanogramStore,
    ShopListLastSucceededSnapshotStore,
    ShopListPublishJournal,
    VisitFinalizedForDayPort,
)
from src.application.micromarket_loading.publish_job import ShopListPublishEventPublisher
from src.application.product_identity.ports import DomainProductStore
from src.application.reference_data import ReferenceDataProvider
from src.application.snack_loading import AcceptSnackInventory
from src.application.snack_loading.ports import (
    KitMatrixDeployMapStore,
    SnackMachineStockStore,
)
from src.config.settings import Settings
from src.domain.form_tokens import (
    build_verify_inventory_form_token,
    build_verify_revision_form_token,
    peek_form_token,
    verify_micromarket_inventory_form_token,
    verify_snack_inventory_form_token,
    verify_technician_warehouse_inventory_token,
)
from src.infrastructure.composition.adapters.complete_open_visit_task import (
    CompleteOpenVisitTaskAdapter,
)
from src.infrastructure.composition.adapters.ensure_open_visit_task import (
    EnsureOpenVisitTaskAdapter,
)
from src.infrastructure.composition.adapters.event_store_visit_finalized_for_day import (
    EventStoreVisitFinalizedForDay,
)
from src.infrastructure.composition.bundles.forms import FormsBundle
from src.infrastructure.composition.bundles.machine_ops import MachineOpsBundle
from src.infrastructure.composition.bundles.technician_warehouse import TechnicianWarehouseBundle
from src.infrastructure.composition.factories import (
    build_form_workflow_session_store,
    build_kit_matrix_deploy_map_store,
    build_machine_sales_store,
    build_micromarket_device_stock_store,
    build_micromarket_planogram_store,
    build_pending_micromarket_invent_store,
    build_service_visit_store,
    build_snack_machine_stock_store,
    build_telegram_user_resolver,
)
from src.infrastructure.micromarket_loading.micromarket_sales_after import (
    MachineSalesMicromarketSalesAfter,
)
from src.infrastructure.snack_loading import DeployMappedSnackSalesAfter
from src.interfaces.google_forms.webhook import (
    GoogleFormsWebhookDeps,
    NoOpDirectWarehouseChatNotifier,
    WebhookPlaceholderBot,
)
from src.interfaces.telegram.form_workflow_notifier import NoOpFormWorkflowNotifier


@beartype
def _build_post_visit_squeeze_enqueue(
    *,
    publisher: ShopListPublishEventPublisher | None,
) -> EnqueuePostVisitSqueezePort:
    """Accept only enqueues outbox (ADR-0065); effects-worker runs PostVisitSqueeze."""
    if publisher is None:
        return InMemoryEnqueuePostVisitSqueeze()
    return OutboxEnqueuePostVisitSqueeze(
        publisher=publisher,  # type: ignore[arg-type]
        clock=lambda: datetime.now(UTC),
    )


@beartype
def wire_forms(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
    machine_ops: MachineOpsBundle,
    product_code_resolver: ProductCodeResolver,
    provider: ReferenceDataProvider,
    technician_warehouse: TechnicianWarehouseBundle,
    form_submission_store: FormSubmissionStore,
    machine_sales_store: MachineSalesStore | None = None,
    snack_stock_store: SnackMachineStockStore | None = None,
    kit_matrix_deploy_map: KitMatrixDeployMapStore | None = None,
    micromarket_stock_store: MicromarketDeviceStockStore | None = None,
    micromarket_planogram_store: MicromarketPlanogramStore | None = None,
    publisher: ShopListPublishEventPublisher | None = None,
    domain_product_store: DomainProductStore | None = None,
    shop_list_publish_journal: ShopListPublishJournal | None = None,
    shop_list_baseline_store: ShopListLastSucceededSnapshotStore | None = None,
) -> FormsBundle:
    google_forms = settings.google_forms
    snack_loading = settings.snack_loading
    micromarket_loading = settings.micromarket_loading
    snack_now_secret = ""
    snack_as_of_secret = ""
    accept_snack_inventory: AcceptSnackInventory | None = None
    if snack_loading.has_any_snack_inventory_forms_env:
        snack_loading.require_snack_inventory_forms()
        assert snack_loading.inventory_form_now_token_secret is not None
        assert snack_loading.inventory_form_as_of_token_secret is not None
        snack_now_secret = snack_loading.inventory_form_now_token_secret.get_secret_value()
        snack_as_of_secret = snack_loading.inventory_form_as_of_token_secret.get_secret_value()
        resolved_stock = snack_stock_store or build_snack_machine_stock_store(
            settings,
            client=mongo_client,
        )
        resolved_sales = machine_sales_store or build_machine_sales_store(
            settings,
            client=mongo_client,
        )
        resolved_deploy = kit_matrix_deploy_map or build_kit_matrix_deploy_map_store(
            settings,
            client=mongo_client,
        )
        accept_snack_inventory = AcceptSnackInventory(
            stock_store=resolved_stock,
            sales_after=DeployMappedSnackSalesAfter(
                sales_store=resolved_sales,
                deploy_map=resolved_deploy,
            ),
        )
    micromarket_now_secret = ""
    micromarket_as_of_secret = ""
    accept_micromarket_inventory: AcceptMicromarketInventory | None = None
    if micromarket_loading.has_any_micromarket_inventory_forms_env:
        if micromarket_loading.is_micromarket_inventory_forms_configured:
            micromarket_loading.require_micromarket_inventory_forms()
        elif (
            micromarket_loading.is_micromarket_inventory_now_configured
            or bool(micromarket_loading.field_forms_public_base_url.strip())
            or (
                micromarket_loading.inventory_form_now_token_secret is not None
                and bool(micromarket_loading.inventory_form_now_token_secret.get_secret_value())
            )
        ):
            micromarket_loading.require_micromarket_inventory_now()
        else:
            micromarket_loading.require_micromarket_inventory_forms()
        if micromarket_loading.inventory_form_now_token_secret is not None:
            micromarket_now_secret = (
                micromarket_loading.inventory_form_now_token_secret.get_secret_value()
            )
        if micromarket_loading.inventory_form_as_of_token_secret is not None:
            micromarket_as_of_secret = (
                micromarket_loading.inventory_form_as_of_token_secret.get_secret_value()
            )
        if micromarket_now_secret or micromarket_as_of_secret:
            resolved_mm_stock: MicromarketDeviceStockStore = (
                micromarket_stock_store
                if micromarket_stock_store is not None
                else build_micromarket_device_stock_store(settings, client=mongo_client)
            )
            resolved_mm_planogram: MicromarketPlanogramStore = (
                micromarket_planogram_store
                if micromarket_planogram_store is not None
                else build_micromarket_planogram_store(settings, client=mongo_client)
            )
            calendar_tz = settings.service_calendar.zone_info()
            calendar_end_hour = settings.service_calendar.service_day_end_hour
            visit_store = build_service_visit_store(settings, client=mongo_client)
            pending_store = build_pending_micromarket_invent_store(
                settings,
                client=mongo_client,
            )
            visit_finalized: VisitFinalizedForDayPort = EventStoreVisitFinalizedForDay(
                event_store=machine_ops.event_store,
                timezone=calendar_tz,
                day_end_hour=calendar_end_hour,
                visit_store=visit_store,
                pending_store=pending_store,
                stock_store=resolved_mm_stock,
            )
            ensure_open_visit: EnsureOpenVisitTaskPort = EnsureOpenVisitTaskAdapter(
                store=visit_store,
                timezone=calendar_tz,
                day_end_hour=calendar_end_hour,
            )
            complete_open_visit: CompleteOpenVisitTaskPort = CompleteOpenVisitTaskAdapter(
                store=visit_store,
                timezone=calendar_tz,
                day_end_hour=calendar_end_hour,
            )
            resolved_mm_sales = machine_sales_store or build_machine_sales_store(
                settings,
                client=mongo_client,
            )
            enqueue_squeeze = _build_post_visit_squeeze_enqueue(publisher=publisher)
            accept_micromarket_inventory = AcceptMicromarketInventory(
                stock_store=resolved_mm_stock,
                sales_after=MachineSalesMicromarketSalesAfter(sales_store=resolved_mm_sales),
                cycle_store=machine_ops.micromarket_loading_cycle_store,
                planogram_store=resolved_mm_planogram,
                publisher=publisher,
                products=domain_product_store,
                journal=shop_list_publish_journal,
                baseline_store=shop_list_baseline_store,
                visit_finalized=visit_finalized,
                ensure_open_visit=ensure_open_visit,
                complete_open_visit=complete_open_visit,
                enqueue_squeeze=enqueue_squeeze,
                pending_store=pending_store,
                timezone=calendar_tz,
                day_end_hour=calendar_end_hour,
            )
    submission_store = form_submission_store
    register_revision_from_form = RegisterRevisionFromFormService(
        executor=machine_ops.executor,
    )
    register_loading_from_form = RegisterLoadingFromFormService(
        executor=machine_ops.executor,
    )
    telegram_user_resolver = build_telegram_user_resolver(provider)
    accept_revision = AcceptRevisionFormSubmissionService(
        form_submission_store=submission_store,
        register_revision_from_form=register_revision_from_form,
        product_code_resolver=product_code_resolver,
        form_token_field_name=google_forms.token_field_name,
    )
    accept_inventory = AcceptInventoryFormSubmissionService(
        form_submission_store=submission_store,
        register_loading_from_form=register_loading_from_form,
        product_code_resolver=product_code_resolver,
        form_token_field_name=google_forms.token_field_name,
    )
    return FormsBundle(
        submission_store=submission_store,
        workflow_session_store=build_form_workflow_session_store(
            settings,
            client=mongo_client,
        ),
        telegram_user_resolver=telegram_user_resolver,
        accept_revision=accept_revision,
        accept_inventory=accept_inventory,
        webhook_deps=GoogleFormsWebhookDeps(
            accept_revision_form_submission=accept_revision,
            accept_technician_warehouse_inventory=technician_warehouse.accept_inventory,
            accept_inventory_form_submission=accept_inventory,
            form_workflow_notifier=FormWorkflowNotifierRef(NoOpFormWorkflowNotifier()),
            direct_warehouse_chat_notifier=NoOpDirectWarehouseChatNotifier(),
            telegram_user_resolver=telegram_user_resolver,
            bot=WebhookPlaceholderBot(),
            token_field_name=google_forms.token_field_name,
            webhook_secret=google_forms.webhook_secret.get_secret_value(),
            webhook_signature_max_age_seconds=google_forms.webhook_signature_max_age_seconds,
            webhook_max_body_bytes=google_forms.webhook_max_body_bytes,
            revision_form_token_secret=google_forms.revision_form_token_secret.get_secret_value(),
            inventory_form_token_secret=google_forms.loading_form_token_secret.get_secret_value(),
            technician_warehouse_inventory_form_token_secret=(
                google_forms.technician_warehouse_inventory_form_token_secret.get_secret_value()
            ),
            verify_revision_form_token=build_verify_revision_form_token(
                max_age_hours=google_forms.form_token_ttl_hours,
            ),
            verify_inventory_form_token=build_verify_inventory_form_token(
                max_age_hours=google_forms.form_token_ttl_hours,
            ),
            verify_technician_warehouse_inventory_token=verify_technician_warehouse_inventory_token,
            peek_form_token=peek_form_token,
            accept_snack_inventory=accept_snack_inventory,
            snack_inventory_now_form_token_secret=snack_now_secret,
            snack_inventory_as_of_form_token_secret=snack_as_of_secret,
            verify_snack_inventory_form_token=verify_snack_inventory_form_token,
            accept_micromarket_inventory=accept_micromarket_inventory,
            micromarket_inventory_now_form_token_secret=micromarket_now_secret,
            micromarket_inventory_as_of_form_token_secret=micromarket_as_of_secret,
            verify_micromarket_inventory_form_token=verify_micromarket_inventory_form_token,
            inventory_form_qty_max=google_forms.inventory_form_qty_max,
        ),
    )
