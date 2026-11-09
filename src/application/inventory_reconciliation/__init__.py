from __future__ import annotations

from src.application.inventory_reconciliation.backfill_missing_sales import (
    BackfillMissingSalesFromKit,
    BackfillMissingSalesFromKitResult,
)
from src.application.inventory_reconciliation.backfill_sale_prices import (
    PRICE_BACKFILL_CUTOVER,
    BackfillSalePricesFromKit,
    BackfillSalePricesFromKitResult,
)
from src.application.inventory_reconciliation.backfill_sales_company_id import (
    BackfillSalesCompanyIdResult,
    backfill_sales_company_id,
)
from src.application.inventory_reconciliation.close_period import (
    CloseResponsibilityPeriodOnRevision,
    build_period_snapshot,
)
from src.application.inventory_reconciliation.company_occupancy import (
    MachineCompanyOccupancy,
    MachineCompanyOccupancyStore,
    rebuild_company_occupancy,
)
from src.application.inventory_reconciliation.create_daily_sales_demands import (
    CreateDailySalesDemands,
    IngestCursorNotReady,
    SellableCatalogNotReady,
    UnresolvedSellableCodesError,
    UnresolvedStoreCodesError,
)
from src.application.inventory_reconciliation.current_company import (
    open_company_id,
    resolve_current_company_name,
)
from src.application.inventory_reconciliation.discover_kitshop_sales import (
    DiscoverKitShopSales,
    DiscoverKitShopSalesResult,
)
from src.application.inventory_reconciliation.drain_kitshop_sales import (
    DrainKitShopSalesBacklog,
    DrainKitShopSalesBacklogResult,
)
from src.application.inventory_reconciliation.import_sales import (
    ImportKitVendingSales,
    ImportKitVendingSalesResult,
)
from src.application.inventory_reconciliation.kitshop_source_id import (
    build_kitshop_sale_source_id,
)
from src.application.inventory_reconciliation.kitvending import (
    HOLDING_SKIP_ALERT_SAMPLE_SIZE,
    HoldingSkipSample,
    KitSalePriceRow,
    KitSaleResolveSkip,
    KitSaleResolveSuccess,
    KitVendingFetchStats,
    KitVendingSaleRow,
    RawKitSaleIdentity,
    ReasonClass,
)
from src.application.inventory_reconciliation.period_errors import (
    PeriodReconciliationNotFound,
    PeriodSnapshotNotReadyError,
)
from src.application.inventory_reconciliation.period_snapshot_recalculate import (
    recalculate_snapshot,
)
from src.application.inventory_reconciliation.ports import PeriodPartyNamesLookup
from src.application.inventory_reconciliation.rebuild_periods import RebuildPeriodSnapshots
from src.application.inventory_reconciliation.recalculate_periods import RecalculatePeriodSnapshots
from src.application.inventory_reconciliation.refresh_pending import (
    RefreshPendingPeriodReconciliations,
    RefreshPendingResult,
)
from src.application.inventory_reconciliation.refresh_targets import (
    compute_machines_to_refresh,
)
from src.application.inventory_reconciliation.resolvers import MappingVendingMachineCodeResolver
from src.application.inventory_reconciliation.sale_skip import MachineSaleSkip, SaleSkipReasonClass
from src.application.inventory_reconciliation.sale_skip_ports import MachineSaleSkipStore
from src.application.inventory_reconciliation.sellable_assortment_ports import (
    SellableProductCodeCatalog,
)
from src.application.inventory_reconciliation.verify_company_occupancy import (
    OccupancyVerifyMismatch,
    RebuildOccupancyResult,
    VerifyOccupancyResult,
    rebuild_company_occupancy_from_sales,
    verify_company_occupancy,
)
from src.application.inventory_reconciliation.verify_portion_sales import (
    VerifyPortionSales,
    VerifyPortionSalesHoldingError,
    VerifyPortionSalesResult,
)

__all__ = [
    "HOLDING_SKIP_ALERT_SAMPLE_SIZE",
    "PRICE_BACKFILL_CUTOVER",
    "BackfillMissingSalesFromKit",
    "BackfillMissingSalesFromKitResult",
    "BackfillSalesCompanyIdResult",
    "backfill_sales_company_id",
    "BackfillSalePricesFromKit",
    "BackfillSalePricesFromKitResult",
    "CloseResponsibilityPeriodOnRevision",
    "CreateDailySalesDemands",
    "DiscoverKitShopSales",
    "DiscoverKitShopSalesResult",
    "DrainKitShopSalesBacklog",
    "DrainKitShopSalesBacklogResult",
    "HoldingSkipSample",
    "ImportKitVendingSales",
    "ImportKitVendingSalesResult",
    "IngestCursorNotReady",
    "build_kitshop_sale_source_id",
    "KitSalePriceRow",
    "KitSaleResolveSkip",
    "KitSaleResolveSuccess",
    "KitVendingFetchStats",
    "KitVendingSaleRow",
    "MachineCompanyOccupancy",
    "MachineCompanyOccupancyStore",
    "MachineSaleSkip",
    "MachineSaleSkipStore",
    "MappingVendingMachineCodeResolver",
    "PeriodPartyNamesLookup",
    "PeriodReconciliationNotFound",
    "PeriodSnapshotNotReadyError",
    "RawKitSaleIdentity",
    "ReasonClass",
    "RecalculatePeriodSnapshots",
    "RebuildPeriodSnapshots",
    "RefreshPendingPeriodReconciliations",
    "RefreshPendingResult",
    "SaleSkipReasonClass",
    "SellableCatalogNotReady",
    "SellableProductCodeCatalog",
    "UnresolvedSellableCodesError",
    "UnresolvedStoreCodesError",
    "VerifyPortionSales",
    "VerifyPortionSalesHoldingError",
    "VerifyPortionSalesResult",
    "OccupancyVerifyMismatch",
    "VerifyOccupancyResult",
    "verify_company_occupancy",
    "RebuildOccupancyResult",
    "rebuild_company_occupancy_from_sales",
    "build_period_snapshot",
    "compute_machines_to_refresh",
    "open_company_id",
    "recalculate_snapshot",
    "rebuild_company_occupancy",
    "resolve_current_company_name",
]
