from __future__ import annotations

from typing import Any

from beartype import beartype
from pymongo import MongoClient

from src.application.coffee_bom.ports import CoffeeRecipeRepository
from src.application.form_submissions.ports import FormSubmissionStore
from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancyStore,
)
from src.application.inventory_reconciliation.ports import (
    MachineRevisionHistoryReader,
    MachineSalesStore,
    ResponsibilityPeriodReconciliationRepository,
)
from src.application.inventory_reconciliation.refresh_pending import (
    RefreshPendingPeriodReconciliations,
)
from src.application.inventory_reconciliation.sale_skip_ports import MachineSaleSkipStore
from src.application.matrix_automation.ports import MatrixPriceSnapshotStore
from src.application.product_identity.ports import DomainProductStore
from src.application.snack_loading import ApplySnackSaleToStock
from src.application.snack_loading.ports import (
    KitMatrixDeployMapStore,
    SnackMachineStockStore,
)
from src.application.technician_settlement import (
    InMemorySettlementAnalysisPrefsStore,
    SettlementAnalysisPrefsStore,
)
from src.application.technician_settlement.draft_ports import ReconciliationDraftStore
from src.application.technician_settlement.executor import TechnicianSettlementExecutor
from src.application.technician_settlement.exit_reconciliation import (
    ExitReconciliationBlockersPort,
    FinalizeExitTechnicianReconciliation,
    PreviewExitTechnicianReconciliation,
)
from src.application.technician_settlement.finalize_reconciliation import (
    TechnicianWarehouseSessionFinalizePort,
)
from src.application.technician_settlement.ports import TechnicianSettlementRepository
from src.application.technician_settlement.post_accountability import PostPeriodAccountability
from src.application.technician_settlement.reconciliation_planner import (
    ReconciliationSessionPlanner,
)
from src.application.technician_settlement.residual_ports import (
    ReconciliationResidualDocumentRepository,
)
from src.application.technician_warehouse import ImportTechnicianWarehouseTransfers
from src.application.technician_warehouse.executor import TechnicianWarehouseExecutor
from src.application.technician_warehouse.ports import (
    TechnicianWarehouseDeltaPort,
    TechnicianWarehouseRepository,
)
from src.config.settings import Settings
from src.infrastructure.composition.adapters.warehouse_session_finalize import (
    WarehouseSessionFinalizeAdapter,
)
from src.infrastructure.composition.factories.persistence import (
    build_event_store,
    build_form_submission_store,
    build_matrix_snapshot_store,
)
from src.infrastructure.composition.refresh_pending_with_accountability import (
    RefreshPendingWithAccountability,
)
from src.infrastructure.machine_revision_history import EventStoreMachineRevisionHistoryReader
from src.infrastructure.mongodb.coffee_recipes import MongoCoffeeRecipeRepository
from src.infrastructure.mongodb.kit_matrix_deploy_map import MongoKitMatrixDeployMapStore
from src.infrastructure.mongodb.machine_company_occupancy import MongoMachineCompanyOccupancyStore
from src.infrastructure.mongodb.machine_sales import MongoMachineSalesStore
from src.infrastructure.mongodb.machine_sales_skipped import MongoMachineSaleSkipStore
from src.infrastructure.mongodb.reconciliation_drafts import MongoReconciliationDraftStore
from src.infrastructure.mongodb.reconciliation_residual_documents import (
    MongoReconciliationResidualDocumentRepository,
)
from src.infrastructure.mongodb.responsibility_period_reconciliations import (
    MongoPeriodReconciliationRepository,
)
from src.infrastructure.mongodb.settlement_analysis_prefs import (
    MongoSettlementAnalysisPrefsStore,
)
from src.infrastructure.mongodb.snack_machine_stock import MongoSnackMachineStockStore
from src.infrastructure.mongodb.technician_settlement import (
    MongoTechnicianSettlementEventStore,
    MongoTechnicianSettlementRepository,
)
from src.infrastructure.testing.coffee_recipe_fakes import InMemoryCoffeeRecipeRepository
from src.infrastructure.testing.company_occupancy_fakes import InMemoryMachineCompanyOccupancyStore
from src.infrastructure.testing.machine_sales_skipped_fakes import InMemoryMachineSaleSkipStore
from src.infrastructure.testing.reconciliation_draft_fakes import InMemoryReconciliationDraftStore
from src.infrastructure.testing.settlement_fakes import (
    InMemoryMachineSalesStore,
    InMemoryPeriodReconciliationRepository,
    InMemoryTechnicianSettlementEventStore,
    InMemoryTechnicianSettlementRepository,
)
from src.infrastructure.testing.snack_loading_fakes import (
    InMemoryKitMatrixDeployMapStore,
    InMemorySnackMachineStockStore,
)


@beartype
def build_machine_sales_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MachineSalesStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMachineSalesStore.from_settings(mongo, client=client)
    return InMemoryMachineSalesStore()


@beartype
def build_machine_company_occupancy_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MachineCompanyOccupancyStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMachineCompanyOccupancyStore.from_settings(mongo, client=client)
    return InMemoryMachineCompanyOccupancyStore()


@beartype
def build_machine_sale_skip_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> MachineSaleSkipStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoMachineSaleSkipStore.from_settings(mongo, client=client)
    return InMemoryMachineSaleSkipStore()


@beartype
def build_snack_machine_stock_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> SnackMachineStockStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoSnackMachineStockStore.from_settings(mongo, client=client)
    return InMemorySnackMachineStockStore()


@beartype
def build_kit_matrix_deploy_map_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> KitMatrixDeployMapStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoKitMatrixDeployMapStore.from_settings(mongo, client=client)
    return InMemoryKitMatrixDeployMapStore()


@beartype
def build_coffee_recipe_repository(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> CoffeeRecipeRepository:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoCoffeeRecipeRepository.from_settings(mongo, client=client)
    return InMemoryCoffeeRecipeRepository()


@beartype
def build_period_reconciliation_repository(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> ResponsibilityPeriodReconciliationRepository:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoPeriodReconciliationRepository.from_settings(mongo, client=client)
    return InMemoryPeriodReconciliationRepository()


@beartype
def build_technician_settlement_repository(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> TechnicianSettlementRepository:
    mongo = settings.mongodb
    if mongo.is_configured:
        event_store = MongoTechnicianSettlementEventStore.from_settings(mongo, client=client)
        return MongoTechnicianSettlementRepository(event_store=event_store)
    return InMemoryTechnicianSettlementRepository(
        event_store=InMemoryTechnicianSettlementEventStore(),
    )


@beartype
def build_settlement_analysis_prefs_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> SettlementAnalysisPrefsStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoSettlementAnalysisPrefsStore.from_settings(
            mongo,
            settings.settlement_analysis,
            client=client,
        )
    return InMemorySettlementAnalysisPrefsStore()


@beartype
def build_reconciliation_residual_document_repository(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> ReconciliationResidualDocumentRepository:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoReconciliationResidualDocumentRepository.from_settings(mongo, client=client)
    raise ValueError("reconciliation residual repository requires MongoDB")


@beartype
def build_reconciliation_draft_store(
    settings: Settings,
    *,
    client: MongoClient[dict[str, Any]] | None = None,
) -> ReconciliationDraftStore:
    mongo = settings.mongodb
    if mongo.is_configured:
        return MongoReconciliationDraftStore.from_settings(mongo, client=client)
    return InMemoryReconciliationDraftStore()


@beartype
def build_reconciliation_session_planner(
    *,
    warehouse_delta_port: TechnicianWarehouseDeltaPort,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    settlement_repository: TechnicianSettlementRepository,
    warehouse_repository: TechnicianWarehouseRepository,
    importer: ImportTechnicianWarehouseTransfers,
) -> ReconciliationSessionPlanner:
    return ReconciliationSessionPlanner(
        warehouse_delta_port=warehouse_delta_port,
        reconciliation_repo=reconciliation_repo,
        settlement_repository=settlement_repository,
        warehouse_repository=warehouse_repository,
        importer=importer,
    )


@beartype
def build_warehouse_session_finalize_adapter(
    *,
    executor: TechnicianWarehouseExecutor,
) -> WarehouseSessionFinalizeAdapter:
    return WarehouseSessionFinalizeAdapter(executor=executor)


@beartype
def build_preview_exit_technician_reconciliation(
    *,
    warehouse_repository: TechnicianWarehouseRepository,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    blockers: ExitReconciliationBlockersPort,
    draft_store: ReconciliationDraftStore,
) -> PreviewExitTechnicianReconciliation:
    return PreviewExitTechnicianReconciliation(
        warehouse_repository=warehouse_repository,
        reconciliation_repo=reconciliation_repo,
        blockers=blockers,
        draft_store=draft_store,
    )


@beartype
def build_finalize_exit_technician_reconciliation(
    *,
    warehouse_repository: TechnicianWarehouseRepository,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository,
    settlement_executor: TechnicianSettlementExecutor,
    settlement_repository: TechnicianSettlementRepository,
    residual_repo: ReconciliationResidualDocumentRepository,
    warehouse_finalize: TechnicianWarehouseSessionFinalizePort,
    draft_store: ReconciliationDraftStore,
) -> FinalizeExitTechnicianReconciliation:
    return FinalizeExitTechnicianReconciliation(
        warehouse_repository=warehouse_repository,
        reconciliation_repo=reconciliation_repo,
        settlement_executor=settlement_executor,
        settlement_repository=settlement_repository,
        residual_repo=residual_repo,
        warehouse_finalize=warehouse_finalize,
        draft_store=draft_store,
    )


@beartype
def _product_from_matrix_snapshot(
    snapshot_store: MatrixPriceSnapshotStore,
    *,
    machine_code: str,
    logical_matrix_name: str,
    line_number: int | None,
) -> str | None:
    if line_number is None:
        return None
    document = snapshot_store.get_latest_line(
        machine_code=machine_code,
        logical_matrix_name=logical_matrix_name,
        line_number=line_number,
    )
    if document is None:
        return None
    for line in document.lines:
        if line.line_number == line_number:
            return line.product_code
    return None


@beartype
def build_apply_snack_sale(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
    stock_store: SnackMachineStockStore | None = None,
    deploy_map: KitMatrixDeployMapStore | None = None,
    snapshot_store: MatrixPriceSnapshotStore | None = None,
) -> ApplySnackSaleToStock:
    resolved_stock = stock_store or build_snack_machine_stock_store(
        settings,
        client=mongo_client,
    )
    resolved_deploy_map = deploy_map or build_kit_matrix_deploy_map_store(
        settings,
        client=mongo_client,
    )
    resolved_snapshot = snapshot_store or build_matrix_snapshot_store(
        settings,
        client=mongo_client,
    )

    @beartype
    def snapshot_product_lookup(
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int | None,
        product_code: str,
    ) -> str | None:
        del product_code
        return _product_from_matrix_snapshot(
            resolved_snapshot,
            machine_code=machine_code,
            logical_matrix_name=logical_matrix_name,
            line_number=line_number,
        )

    return ApplySnackSaleToStock(
        stock_store=resolved_stock,
        deploy_map=resolved_deploy_map,
        snapshot_product_lookup=snapshot_product_lookup,
    )


@beartype
def build_refresh_pending_with_accountability(
    settings: Settings,
    *,
    mongo_client: MongoClient[dict[str, Any]] | None,
    domain_product_store: DomainProductStore,
    reconciliation_repo: ResponsibilityPeriodReconciliationRepository | None = None,
    sales_store: MachineSalesStore | None = None,
    coffee_recipe_repo: CoffeeRecipeRepository | None = None,
    form_submission_store: FormSubmissionStore | None = None,
    revision_history: MachineRevisionHistoryReader | None = None,
    technician_settlement_repository: TechnicianSettlementRepository | None = None,
    post_accountability: PostPeriodAccountability | None = None,
) -> RefreshPendingWithAccountability:
    resolved_reconciliation_repo = reconciliation_repo or build_period_reconciliation_repository(
        settings,
        client=mongo_client,
    )
    resolved_sales_store = sales_store or build_machine_sales_store(settings, client=mongo_client)
    resolved_coffee_recipe_repo = coffee_recipe_repo or build_coffee_recipe_repository(
        settings,
        client=mongo_client,
    )
    resolved_form_submission_store = form_submission_store or build_form_submission_store(
        settings,
        client=mongo_client,
    )
    resolved_revision_history = revision_history or EventStoreMachineRevisionHistoryReader(
        event_store=build_event_store(settings, client=mongo_client),
    )
    resolved_post_accountability = post_accountability or PostPeriodAccountability(
        settlement_executor=TechnicianSettlementExecutor(
            repository=(
                technician_settlement_repository
                or build_technician_settlement_repository(settings, client=mongo_client)
            ),
        ),
        reconciliation_repo=resolved_reconciliation_repo,
    )
    refresh_pending = RefreshPendingPeriodReconciliations(
        repo=resolved_reconciliation_repo,
        sales_store=resolved_sales_store,
        coffee_recipe_repo=resolved_coffee_recipe_repo,
        domain_product_store=domain_product_store,
        form_submission_store=resolved_form_submission_store,
        revision_history=resolved_revision_history,
        tolerance_seconds=settings.settlement.sales_coverage_tolerance_seconds,
    )
    return RefreshPendingWithAccountability(
        refresh=refresh_pending,
        post_accountability=resolved_post_accountability,
    )
