from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation import (
    BuildMatrixDeployResult,
    MatrixParseState,
    MatrixReferenceDataProvider,
    PurchaseFetchGlobalAbort,
    RunMatrixDeployBuild,
)
from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.ports import (
    MatrixBaseMarginStore,
    MatrixPriceSnapshotStore,
    MatrixSkuCatalogStore,
    MatrixStockProvider,
    PurchaseAttributesReader,
)


@beartype
@dataclass(slots=True)
class ProviderBackedRunMatrixDeployBuild:
    snapshot_store: MatrixPriceSnapshotStore
    purchase_reader: PurchaseAttributesReader
    provider: MatrixReferenceDataProvider
    blocking_cell_price: Decimal
    max_price_delta_pct: Decimal
    substitution_guard_enabled: bool
    stock_provider: MatrixStockProvider | None
    base_margin_store: MatrixBaseMarginStore
    seed_only: bool = False
    sku_catalog_master_enabled: bool = False
    sku_catalog_store: MatrixSkuCatalogStore | None = None

    @beartype
    def __call__(
        self,
        state: MatrixParseState,
        *,
        job_id: str = "test",
        seed_only: bool = False,
    ) -> BuildMatrixDeployResult | PurchaseFetchGlobalAbort:
        base_margin = self.base_margin_store.get()
        if base_margin is None:
            return PurchaseFetchGlobalAbort(reason="base_margin_not_loaded")
        effective_seed_only = seed_only or self.seed_only
        sku_catalog_by_code: dict[str, MatrixSkuCatalogEntry] | None = None
        product_multipliers = self.provider.product_multipliers
        if self.sku_catalog_master_enabled:
            store = self.sku_catalog_store
            if store is None:
                raise ValueError(
                    "MatrixSkuCatalogStore required when MATRIX_SKU_CATALOG_MASTER_ENABLED=true"
                )
            sku_catalog_by_code = {entry.product_code: entry for entry in store.list_all()}
        runner = RunMatrixDeployBuild(
            snapshot_store=self.snapshot_store,
            purchase_reader=self.purchase_reader,
            blocking_cell_price=self.blocking_cell_price,
            max_price_delta_pct=self.max_price_delta_pct,
            base_margin=base_margin,
            product_multipliers=product_multipliers,
            substitution_guard_enabled=self.substitution_guard_enabled,
            stock_provider=self.stock_provider,
            seed_only=effective_seed_only,
            sku_catalog_by_code=sku_catalog_by_code,
        )
        return runner(state, job_id=job_id)
