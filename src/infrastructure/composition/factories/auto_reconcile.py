from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation import (
    RefreshPendingPeriodReconciliations,
    VerifyPortionSales,
)
from src.application.inventory_reconciliation.ports import (
    KitPortionSalesGateway,
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.inventory_reconciliation.resolvers import IdentityVendingMachineCodeResolver
from src.application.machine_operations.ports import DomainEventPublisher, VendingMachineRepository
from src.application.outbox.settlement_portion_reconcile import (
    SettlementPortionReconcileHandler,
)
from src.application.outbox.settlement_portion_sales_verify import (
    SettlementPortionSalesVerifyHandler,
)
from src.application.outbox.settlement_portion_sync_transfers import (
    SettlementPortionSyncTransfersHandler,
)
from src.application.product_identity.ports import DomainProductStore
from src.application.reference_data import ReferenceDataProvider
from src.application.technician_settlement import (
    FinalizeTechnicianReconciliation,
    PreviewTechnicianReconciliation,
    TechnicianSettlementExecutor,
)
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.application.technician_settlement.residual_ports import (
    ReconciliationResidualDocumentRepository,
)
from src.application.technician_warehouse import (
    ImportTechnicianWarehouseTransfers,
    TechnicianWarehouseDeltaService,
)
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.config.settings import Settings
from src.infrastructure.composition.adapters.border_unregistered_ops_alerter import (
    build_border_unregistered_ops_alerter,
)
from src.infrastructure.composition.adapters.finalized_transfer_drift_ops_alerter import (
    build_finalized_transfer_drift_ops_alerter,
)
from src.infrastructure.composition.adapters.machine_pnl_finalize_hook import (
    FinalizeReconciliationPort,
    FinalizeWithMachinePnlEnqueue,
)
from src.infrastructure.composition.adapters.warehouse_session_finalize import (
    WarehouseSessionFinalizeAdapter,
)
from src.infrastructure.composition.factories.companies import build_company_store
from src.infrastructure.composition.factories.integrations import (
    build_kitvending_client,
    build_kitvending_request_id_store,
)
from src.infrastructure.composition.factories.product_identity import (
    build_domain_product_resolver,
)
from src.infrastructure.composition.factories.settlement import (
    build_machine_sale_skip_store,
    build_reconciliation_draft_store,
    build_reconciliation_residual_document_repository,
    build_reconciliation_session_planner,
    build_warehouse_session_finalize_adapter,
)
from src.infrastructure.composition.refresh_pending_with_accountability import (
    RefreshPendingWithAccountability,
)
from src.infrastructure.machine_revision_history import EventStoreMachineRevisionHistoryReader


@beartype
@dataclass(frozen=True, slots=True)
class SettlementPortionHandlers:
    sync: SettlementPortionSyncTransfersHandler
    sales_verify: SettlementPortionSalesVerifyHandler
    reconcile: SettlementPortionReconcileHandler


@beartype
def build_settlement_portion_handlers(
    settings: Settings,
    *,
    publisher: DomainEventPublisher,
    importer: ImportTechnicianWarehouseTransfers,
    warehouse_executor: TechnicianWarehouseExecutor,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    settlement_repository: TechnicianSettlementRepository,
    machine_sales_store: MachineSalesStore,
    coffee_recipe_repo: CoffeeRecipeRepository,
    domain_product_store: DomainProductStore,
    form_submission_store: FormSubmissionStore,
    revision_history: EventStoreMachineRevisionHistoryReader,
    post_accountability: PostPeriodAccountability,
    vending_machines: VendingMachineRepository,
    reference_provider: ReferenceDataProvider,
    client: MongoClient[dict[str, Any]] | None = None,
) -> SettlementPortionHandlers | None:
    if not settings.settlement.auto_reconcile_enabled:
        return None
    if not settings.mongodb.is_configured:
        raise ValueError(
            "SETTLEMENT_AUTO_RECONCILE_ENABLED requires MONGODB_URI",
        )

    skip_store = build_machine_sale_skip_store(settings, client=client)
    request_id_store = build_kitvending_request_id_store(
        settings,
        mongo_client=client,
    )
    company_store = build_company_store(settings, mongo_client=client)
    kit_client = build_kitvending_client(
        settings.kitvending,
        request_id_store=request_id_store,
        skip_store=skip_store,
        company_store=company_store,
        domain_product_identity_enabled=settings.domain_product_identity.enabled,
        resolve_sale_code=build_domain_product_resolver(
            settings,
            reference_provider,
            client=client,
        ),
    )
    if not isinstance(kit_client, KitPortionSalesGateway):
        raise ValueError(
            "SETTLEMENT_AUTO_RECONCILE_ENABLED requires a configured KitVending client "
            "with portion sales gateway (fetch_raw_window / resolve)",
        )

    refresh = RefreshPendingWithAccountability(
        refresh=RefreshPendingPeriodReconciliations(
            repo=reconciliation_repo,
            sales_store=machine_sales_store,
            coffee_recipe_repo=coffee_recipe_repo,
            domain_product_store=domain_product_store,
            form_submission_store=form_submission_store,
            revision_history=revision_history,
            tolerance_seconds=settings.settlement.sales_coverage_tolerance_seconds,
        ),
        post_accountability=post_accountability,
    )
    verifier = VerifyPortionSales(
        sales_store=machine_sales_store,
        kit_gateway=kit_client,
        skip_store=skip_store,
        reconciliation_repo=reconciliation_repo,
        code_resolver=IdentityVendingMachineCodeResolver(),
        refresh=refresh,
    )

    draft_store = build_reconciliation_draft_store(settings, client=client)
    residual_repo = build_reconciliation_residual_document_repository(
        settings,
        client=client,
    )
    delta_port = TechnicianWarehouseDeltaService(
        importer=importer,
        executor=warehouse_executor,
    )
    planner = build_reconciliation_session_planner(
        warehouse_delta_port=delta_port,
        reconciliation_repo=reconciliation_repo,
        settlement_repository=settlement_repository,
        warehouse_repository=warehouse_executor.repository,
        importer=importer,
    )
    warehouse_finalize = build_warehouse_session_finalize_adapter(
        executor=warehouse_executor,
    )
    settlement_executor = TechnicianSettlementExecutor(repository=settlement_repository)
    preview = PreviewTechnicianReconciliation(
        planner=planner,
        draft_store=draft_store,
    )
    finalize = _build_finalize(
        settings=settings,
        publisher=publisher,
        draft_store=draft_store,
        warehouse_executor=warehouse_executor,
        settlement_executor=settlement_executor,
        settlement_repository=settlement_repository,
        reconciliation_repo=reconciliation_repo,
        residual_repo=residual_repo,
        warehouse_finalize=warehouse_finalize,
    )
    drift_ops_alerter = build_finalized_transfer_drift_ops_alerter(settings)
    return SettlementPortionHandlers(
        sync=SettlementPortionSyncTransfersHandler(
            importer=importer,
            publisher=publisher,
            border_ops_alerter=build_border_unregistered_ops_alerter(settings),
            drift_ops_alerter=drift_ops_alerter,
        ),
        sales_verify=SettlementPortionSalesVerifyHandler(
            verifier=verifier,
            publisher=publisher,
            quarantine_seconds=settings.settlement.portion_reconcile_quarantine_seconds,
        ),
        reconcile=SettlementPortionReconcileHandler(
            preview=preview,
            finalize=finalize,
            importer=importer,
            verifier=verifier,
            residual_repo=residual_repo,
            drift_ops_alerter=drift_ops_alerter,
        ),
    )


@beartype
def _build_finalize(
    *,
    settings: Settings,
    publisher: DomainEventPublisher,
    draft_store: ReconciliationDraftStore,
    warehouse_executor: TechnicianWarehouseExecutor,
    settlement_executor: TechnicianSettlementExecutor,
    settlement_repository: TechnicianSettlementRepository,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    residual_repo: ReconciliationResidualDocumentRepository,
    warehouse_finalize: WarehouseSessionFinalizeAdapter,
) -> FinalizeReconciliationPort:
    finalize: FinalizeReconciliationPort = FinalizeTechnicianReconciliation(
        draft_store=draft_store,
        warehouse_repository=warehouse_executor.repository,
        settlement_executor=settlement_executor,
        settlement_repository=settlement_repository,
        reconciliation_repo=reconciliation_repo,
        residual_repo=residual_repo,
        warehouse_finalize=warehouse_finalize,
    )
    if settings.machine_pnl.enabled:
        finalize = FinalizeWithMachinePnlEnqueue(
            inner=finalize,
            reconciliation_repo=reconciliation_repo,
            publisher=publisher,
        )
    return finalize
