"""Matrix automation application layer."""

from src.application.matrix_automation.apply_snack_matrix import (
    ApplySnackMatrix,
    ApplySnackMatrixRejected,
    ApplySnackMatrixResult,
)
from src.application.matrix_automation.base_margin_commands import (
    BaseMarginCommandRejected,
    SaveBaseMargin,
    validate_base_margin_params,
)
from src.application.matrix_automation.base_margin_store_memory import (
    InMemoryMatrixBaseMarginStore,
)
from src.application.matrix_automation.build_deploy_payloads import BuildMatrixDeployPayloads
from src.application.matrix_automation.daily_job import RunDailyMatrixDeployJob
from src.application.matrix_automation.deploy_reasons import (
    BASELINE_ALREADY_PRESENT,
    INCOMPLETE_MATRIX_NO_SNAPSHOT,
    INVALID_MATRIX_HEADER,
    INVALID_MATRIX_MULTIPLIER,
    PRODUCT_REFERENCE_INVALID,
    UNKNOWN_PRODUCT_NAME,
)
from src.application.matrix_automation.errors import PurchasePricesBatchError
from src.application.matrix_automation.human_descriptions import human_description_for
from src.application.matrix_automation.import_matrix_sku_catalog import (
    ImportMatrixSkuCatalog,
    ImportMatrixSkuCatalogInput,
    ImportMatrixSkuCatalogResult,
)
from src.application.matrix_automation.import_snack_layouts import (
    ImportSnackLayouts,
    ImportSnackLayoutsInput,
    ImportSnackLayoutsResult,
)
from src.application.matrix_automation.job_models import (
    JobStatus,
    JobTrigger,
    MatrixDeployJob,
    MatrixDeployJobUnit,
    ProductSwapBlockedLine,
    StrongPriceIncreaseLine,
    UnitStatus,
)
from src.application.matrix_automation.loading_policy import DefaultMatrixCellLoadingPolicy
from src.application.matrix_automation.matrix_sku_catalog import (
    DEFAULT_PRODUCT_MULTIPLIER,
    MatrixSkuCatalogEntry,
    is_matrix_ready,
    resolve_product_multiplier,
)
from src.application.matrix_automation.matrix_sku_catalog_memory import (
    InMemoryMatrixSkuCatalogStore,
)
from src.application.matrix_automation.matrix_sku_commands import (
    BulkSaveMatrixSku,
    BulkSaveMatrixSkuInput,
    BulkSaveMatrixSkuRow,
    EnrollMatrixSku,
    EnrollMatrixSkuInput,
    MatrixSkuCommandRejected,
    SaveMatrixSku,
    SaveMatrixSkuInput,
)
from src.application.matrix_automation.matrix_sku_list import (
    MatrixSkuListRow,
    build_matrix_sku_catalog_rows,
)
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    BlockedProductRef,
    BuildMatrixDeployResult,
    EnabledLogicalMatrix,
    MatrixDeployApplyStatus,
    MatrixDeployFailureReason,
    MatrixDeployPayload,
    MatrixDeployPayloadLine,
    MatrixDeployResult,
    MatrixDeploySkippedUnit,
    MatrixParseState,
    PriceSnapshotDocument,
    PurchaseAttributesFetchResult,
    SkuStats,
    SnapshotLineRecord,
)
from src.application.matrix_automation.planogram_product_code import (
    kit_product_code,
    skipped_product_name,
)
from src.application.matrix_automation.ports import (
    MatrixBaseMarginStore,
    MatrixCellLoadingPolicy,
    MatrixDeployer,
    MatrixDeployJobRepository,
    MatrixJobNotifier,
    MatrixSkuCatalogStore,
    MatrixStockProvider,
    MatrixWorkerStatusRepository,
    RunMatrixDeployBuildPort,
    SnackMachineLayoutStore,
)
from src.application.matrix_automation.provider import MatrixReferenceDataProvider
from src.application.matrix_automation.run_matrix_deploy_build import (
    PurchaseFetchGlobalAbort,
    RunMatrixDeployBuild,
)
from src.application.matrix_automation.sheets.machine_code import (
    extract_vending_machine_code,
    is_inactive_vending_machine_name,
)
from src.application.matrix_automation.sheets.product_multipliers import (
    parse_product_multipliers_sheet,
)
from src.application.matrix_automation.snack_layout_commands import (
    CopySnackLayout,
    CopySnackLayoutInput,
    SaveSnackLayout,
    SaveSnackLayoutInput,
    SnackLayoutCommandRejected,
)
from src.application.matrix_automation.snack_machine_layout import (
    SnackMachineLayout,
    SnackMachineLayoutCell,
)
from src.application.matrix_automation.snack_machine_layout_memory import (
    InMemorySnackMachineLayoutStore,
)
from src.application.matrix_automation.snack_planogram import (
    PlanogramAnchorCell,
    SnackPlanogramMerge,
    default_planogram_dimensions,
)
from src.application.matrix_automation.sync import (
    MatrixCatalogTabReader,
    MatrixReferenceSync,
    MatrixUtilitySync,
    SyncGlobalAbort,
)

__all__ = [
    "ApplySnackMatrix",
    "ApplySnackMatrixRejected",
    "ApplySnackMatrixResult",
    "BuildMatrixDeployPayloads",
    "BuildMatrixDeployResult",
    "BlockedMatrixEntry",
    "BlockedProductRef",
    "BulkSaveMatrixSku",
    "BulkSaveMatrixSkuInput",
    "BulkSaveMatrixSkuRow",
    "CopySnackLayout",
    "CopySnackLayoutInput",
    "DEFAULT_PRODUCT_MULTIPLIER",
    "DefaultMatrixCellLoadingPolicy",
    "default_planogram_dimensions",
    "EnabledLogicalMatrix",
    "EnrollMatrixSku",
    "EnrollMatrixSkuInput",
    "BASELINE_ALREADY_PRESENT",
    "BaseMarginCommandRejected",
    "INCOMPLETE_MATRIX_NO_SNAPSHOT",
    "INVALID_MATRIX_HEADER",
    "INVALID_MATRIX_MULTIPLIER",
    "ImportMatrixSkuCatalog",
    "ImportMatrixSkuCatalogInput",
    "ImportMatrixSkuCatalogResult",
    "ImportSnackLayouts",
    "ImportSnackLayoutsInput",
    "ImportSnackLayoutsResult",
    "InMemoryMatrixBaseMarginStore",
    "InMemoryMatrixSkuCatalogStore",
    "InMemorySnackMachineLayoutStore",
    "JobStatus",
    "JobTrigger",
    "MatrixBaseMarginStore",
    "MatrixCellLoadingPolicy",
    "MatrixDeployApplyStatus",
    "MatrixDeployFailureReason",
    "MatrixDeployJob",
    "MatrixDeployJobRepository",
    "MatrixDeployJobUnit",
    "MatrixDeployPayload",
    "MatrixDeployPayloadLine",
    "MatrixDeployResult",
    "MatrixDeploySkippedUnit",
    "MatrixDeployer",
    "MatrixJobNotifier",
    "MatrixParseState",
    "MatrixCatalogTabReader",
    "MatrixReferenceDataProvider",
    "MatrixReferenceSync",
    "MatrixSkuCatalogEntry",
    "MatrixSkuCatalogStore",
    "MatrixSkuCommandRejected",
    "MatrixSkuListRow",
    "MatrixUtilitySync",
    "MatrixStockProvider",
    "MatrixWorkerStatusRepository",
    "PlanogramAnchorCell",
    "SnackPlanogramMerge",
    "PRODUCT_REFERENCE_INVALID",
    "PriceSnapshotDocument",
    "ProductSwapBlockedLine",
    "PurchaseAttributesFetchResult",
    "PurchaseFetchGlobalAbort",
    "PurchasePricesBatchError",
    "RunDailyMatrixDeployJob",
    "RunMatrixDeployBuild",
    "RunMatrixDeployBuildPort",
    "SaveBaseMargin",
    "SaveMatrixSku",
    "SaveMatrixSkuInput",
    "SaveSnackLayout",
    "SaveSnackLayoutInput",
    "SkuStats",
    "SnapshotLineRecord",
    "SnackLayoutCommandRejected",
    "SnackMachineLayout",
    "SnackMachineLayoutCell",
    "SnackMachineLayoutStore",
    "StrongPriceIncreaseLine",
    "SyncGlobalAbort",
    "UNKNOWN_PRODUCT_NAME",
    "UnitStatus",
    "build_matrix_sku_catalog_rows",
    "extract_vending_machine_code",
    "validate_base_margin_params",
    "human_description_for",
    "is_inactive_vending_machine_name",
    "is_matrix_ready",
    "kit_product_code",
    "parse_product_multipliers_sheet",
    "resolve_product_multiplier",
    "skipped_product_name",
]
