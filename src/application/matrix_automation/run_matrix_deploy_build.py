from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation.build_deploy_payloads import BuildMatrixDeployPayloads
from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.models import BuildMatrixDeployResult, MatrixParseState
from src.application.matrix_automation.ms_union import (
    collect_catalog_product_codes,
    collect_guard_current_product_codes,
    enabled_matrices_with_seed_candidates,
    product_level_blocks_from_missing_skus,
    purchase_fetch_global_abort_reason,
    should_fetch_purchase_attributes,
)
from src.application.matrix_automation.ports import (
    MatrixPriceSnapshotStore,
    MatrixStockProvider,
    PurchaseAttributesReader,
)
from src.domain.matrix_pricing.formula import BaseMarginParams


@beartype
@dataclass(frozen=True, slots=True)
class PurchaseFetchGlobalAbort:
    reason: str


@beartype
@dataclass(slots=True)
class RunMatrixDeployBuild:
    snapshot_store: MatrixPriceSnapshotStore
    purchase_reader: PurchaseAttributesReader
    blocking_cell_price: Decimal
    max_price_delta_pct: Decimal
    base_margin: BaseMarginParams
    product_multipliers: dict[str, Decimal]
    substitution_guard_enabled: bool = False
    stock_provider: MatrixStockProvider | None = None
    seed_only: bool = False
    sku_catalog_by_code: Mapping[str, MatrixSkuCatalogEntry] | None = None

    @beartype
    def __call__(
        self,
        state: MatrixParseState,
        *,
        job_id: str = "test",
        seed_only: bool = False,
    ) -> BuildMatrixDeployResult | PurchaseFetchGlobalAbort:
        effective_seed_only = seed_only or self.seed_only
        matrices_for_ms = (
            enabled_matrices_with_seed_candidates(state, snapshot_store=self.snapshot_store)
            if effective_seed_only
            else state.enabled_matrices
        )
        catalog_codes = collect_catalog_product_codes(
            matrices_for_ms,
            product_block_map=state.product_block_map,
        )
        guard_codes = (
            collect_guard_current_product_codes(
                matrices_for_ms,
                snapshot_store=self.snapshot_store,
            )
            if self.substitution_guard_enabled
            else frozenset()
        )
        codes = catalog_codes | guard_codes
        purchase_attributes: dict[str, tuple[str, int]] = {}
        if should_fetch_purchase_attributes(codes):
            try:
                fetch_result = self.purchase_reader.fetch_attributes(codes)
            except Exception as exc:  # noqa: BLE001
                return PurchaseFetchGlobalAbort(reason=purchase_fetch_global_abort_reason(exc))
            if fetch_result.cards_found == 0:
                return PurchaseFetchGlobalAbort(reason="moysklad_batch_empty_response")
            purchase_attributes = fetch_result.attributes

        ms_blocks = product_level_blocks_from_missing_skus(
            enabled_matrices=state.enabled_matrices,
            requested_codes=codes,
            returned_codes=frozenset(purchase_attributes.keys()),
        )
        effective_state = MatrixParseState(
            enabled_matrices=state.enabled_matrices,
            blocked_matrices=state.blocked_matrices + ms_blocks,
            product_block_map=state.product_block_map,
            auto_sync_disabled_matrices=state.auto_sync_disabled_matrices,
        )
        builder = BuildMatrixDeployPayloads(
            snapshot_store=self.snapshot_store,
            purchase_reader=self.purchase_reader,
            blocking_cell_price=self.blocking_cell_price,
            max_price_delta_pct=self.max_price_delta_pct,
            base_margin=self.base_margin,
            product_multipliers=self.product_multipliers,
            purchase_attributes=purchase_attributes,
            substitution_guard_enabled=self.substitution_guard_enabled,
            stock_provider=self.stock_provider,
            job_id=job_id,
            seed_only=effective_seed_only,
            sku_catalog_by_code=self.sku_catalog_by_code,
        )
        return builder(effective_state)
