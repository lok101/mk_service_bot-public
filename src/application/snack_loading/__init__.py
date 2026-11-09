from __future__ import annotations

from src.application.snack_loading.accept_inventory import AcceptSnackInventory
from src.application.snack_loading.apply_sale import ApplySnackSaleToStock
from src.application.snack_loading.form_fingerprint import inventory_form_fingerprint
from src.application.snack_loading.issue_inventory_link import (
    IssuedSnackInventoryLink,
    IssueSnackInventoryLink,
)
from src.application.snack_loading.loading_plan import (
    SnackLoadingCellInput,
    SnackLoadingPlan,
    compute_snack_loading_plan,
)
from src.application.snack_loading.matrix_stock_provider import DomainMatrixStockProvider
from src.application.snack_loading.ports import (
    CopiedSnackInventoryForm,
    InventoryFormCell,
    KitMatrixDeployMapRow,
    KitMatrixDeployMapStore,
    NoOpSnackSaleUnresolvedAlertNotifier,
    RegisteredSnackInventoryForm,
    ResolvedSaleForReplay,
    SnackInventoryCellsSource,
    SnackInventoryFormFactory,
    SnackInventoryFormMode,
    SnackInventoryFormRegistry,
    SnackInventoryFormsConfig,
    SnackMachineStockStore,
    SnackSalesAfterPort,
    SnackSaleUnresolvedAlertNotifier,
)
from src.application.snack_loading.record_kit_matrix_deploy import record_kit_matrix_deploy
from src.application.snack_loading.resolve_sale import resolve_snack_sale
from src.application.snack_loading.run_loading import (
    LoadingBatchInput,
    RunSnackLoading,
    SnackLoadingRunResult,
)

__all__ = [
    "AcceptSnackInventory",
    "ApplySnackSaleToStock",
    "CopiedSnackInventoryForm",
    "DomainMatrixStockProvider",
    "InventoryFormCell",
    "IssueSnackInventoryLink",
    "IssuedSnackInventoryLink",
    "KitMatrixDeployMapRow",
    "KitMatrixDeployMapStore",
    "LoadingBatchInput",
    "NoOpSnackSaleUnresolvedAlertNotifier",
    "RegisteredSnackInventoryForm",
    "ResolvedSaleForReplay",
    "RunSnackLoading",
    "SnackInventoryCellsSource",
    "SnackInventoryFormFactory",
    "SnackInventoryFormMode",
    "SnackInventoryFormRegistry",
    "SnackInventoryFormsConfig",
    "SnackLoadingCellInput",
    "SnackLoadingPlan",
    "SnackLoadingRunResult",
    "SnackMachineStockStore",
    "SnackSaleUnresolvedAlertNotifier",
    "SnackSalesAfterPort",
    "compute_snack_loading_plan",
    "inventory_form_fingerprint",
    "record_kit_matrix_deploy",
    "resolve_snack_sale",
]
