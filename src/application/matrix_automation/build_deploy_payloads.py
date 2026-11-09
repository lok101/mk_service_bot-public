from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from beartype import beartype

from src.application.matrix_automation.deploy_reasons import (
    BASELINE_ALREADY_PRESENT,
    INCOMPLETE_MATRIX_NO_SNAPSHOT,
)
from src.application.matrix_automation.matrix_sku_catalog import (
    MatrixSkuCatalogEntry,
    is_matrix_ready,
)
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    BuildMatrixDeployResult,
    MatrixDeployPayload,
    MatrixDeployPayloadLine,
    MatrixDeploySkippedUnit,
    MatrixParseState,
    SnapshotLineRecord,
)
from src.application.matrix_automation.ports import (
    MatrixPriceSnapshotStore,
    MatrixStockProvider,
    PurchaseAttributesReader,
)
from src.application.matrix_automation.sku_stats import sku_stats_from_lines
from src.domain.matrix_pricing.blocking import build_blocking_empty_line
from src.domain.matrix_pricing.formula import BaseMarginParams, calculate_sell_price
from src.domain.matrix_pricing.merge import SnapshotLine, merge_sku_price
from src.domain.matrix_pricing.substitution import (
    SubstitutionDecision,
    decide_substitution,
    detect_pending_product_swap,
)

logger = logging.getLogger(__name__)


@beartype
def _snapshot_line_from_record(record: SnapshotLineRecord) -> SnapshotLine:
    return SnapshotLine(
        product_code=record.product_code,
        product_name=record.product_name,
        deploy_price=Decimal(record.deploy_price),
        capacity=record.capacity,
    )


@beartype
def _blocked_empty_payload_line(
    line_number: int,
    blocking_cell_price: Decimal,
) -> MatrixDeployPayloadLine:
    blocking = build_blocking_empty_line(
        line_number=line_number,
        blocking_price=blocking_cell_price,
    )
    return MatrixDeployPayloadLine(
        line_number=blocking.line_number,
        product_code=None,
        product_name="",
        deploy_price=blocking.deploy_price,
        capacity=0,
        outcome="blocked_empty",
        reason=None,
        strong_price_increase=False,
    )


@beartype
@dataclass(slots=True)
class BuildMatrixDeployPayloads:
    snapshot_store: MatrixPriceSnapshotStore
    purchase_reader: PurchaseAttributesReader
    blocking_cell_price: Decimal
    max_price_delta_pct: Decimal
    base_margin: BaseMarginParams
    product_multipliers: dict[str, Decimal]
    purchase_attributes: dict[str, tuple[str, int]]
    substitution_guard_enabled: bool = False
    stock_provider: MatrixStockProvider | None = None
    job_id: str = "test"
    seed_only: bool = False
    sku_catalog_by_code: Mapping[str, MatrixSkuCatalogEntry] | None = None

    @beartype
    def _lookup_purchase_attributes(
        self,
        product_code: str,
    ) -> tuple[str, int] | None:
        return self.purchase_attributes.get(product_code)

    @beartype
    def _decide_product(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
        desired_product: str | None,
        snapshot_line: SnapshotLine | None,
    ) -> SubstitutionDecision | None:
        current = snapshot_line.product_code if snapshot_line is not None else None
        if not self.substitution_guard_enabled or not detect_pending_product_swap(
            desired_product=desired_product,
            snapshot_product=current,
        ):
            return None
        if self.stock_provider is None:
            raise ValueError(
                "MatrixStockProvider required when MATRIX_SUBSTITUTION_GUARD_ENABLED=true"
            )
        assert current is not None
        try:
            observed = self.stock_provider.current_stock(
                machine_code=machine_code,
                logical_matrix_name=logical_matrix_name,
                line_number=line_number,
                product_code=current,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "matrix_stock_fetch_failed",
                extra={
                    "job_id": self.job_id,
                    "machine_code": machine_code,
                    "logical_matrix_name": logical_matrix_name,
                    "line_number": line_number,
                    "product_code": current,
                    "error": str(exc),
                },
            )
            observed = None
        decision = decide_substitution(
            desired_product=desired_product,
            current_product=current,
            observed_stock=observed,
        )
        if decision.blocked:
            logger.info(
                "matrix_substitution_blocked",
                extra={
                    "job_id": self.job_id,
                    "machine_code": machine_code,
                    "logical_matrix_name": logical_matrix_name,
                    "line_number": line_number,
                    "current_product": current,
                    "desired_product": desired_product,
                    "observed_stock": decision.observed_stock,
                    "block_reason": decision.block_reason,
                },
            )
        return decision

    @beartype
    def __call__(self, state: MatrixParseState) -> BuildMatrixDeployResult:
        skipped_units: list[MatrixDeploySkippedUnit] = []
        for blocked in state.blocked_matrices:
            skipped_units.extend(self._blocked_skipped_units(blocked))

        payloads: list[MatrixDeployPayload] = []
        blocked_names = {entry.logical_matrix_name for entry in state.blocked_matrices}

        for matrix in state.enabled_matrices:
            if matrix.logical_matrix_name in blocked_names:
                continue
            for machine_code in matrix.machine_codes:
                payload_or_skip = self._build_unit(
                    matrix=matrix,
                    machine_code=machine_code,
                )
                if isinstance(payload_or_skip, MatrixDeployPayload):
                    payloads.append(payload_or_skip)
                else:
                    skipped_units.append(payload_or_skip)

        return BuildMatrixDeployResult(
            payloads=tuple(payloads),
            skipped_units=tuple(skipped_units),
        )

    @beartype
    def _blocked_skipped_units(
        self,
        blocked: BlockedMatrixEntry,
    ) -> list[MatrixDeploySkippedUnit]:
        if not blocked.machine_codes:
            return []
        return [
            MatrixDeploySkippedUnit(
                logical_matrix_name=blocked.logical_matrix_name,
                machine_code=machine_code,
                deploy_status="skipped",
                deploy_reason=blocked.deploy_reason,
                sku_stats=None,
            )
            for machine_code in blocked.machine_codes
        ]

    @beartype
    def _build_unit(
        self,
        *,
        matrix: object,
        machine_code: str,
    ) -> MatrixDeployPayload | MatrixDeploySkippedUnit:
        from src.application.matrix_automation.models import EnabledLogicalMatrix

        assert isinstance(matrix, EnabledLogicalMatrix)
        if self.seed_only and self.snapshot_store.has_unit_snapshot(
            machine_code=machine_code,
            logical_matrix_name=matrix.logical_matrix_name,
        ):
            return MatrixDeploySkippedUnit(
                logical_matrix_name=matrix.logical_matrix_name,
                machine_code=machine_code,
                deploy_status="skipped",
                deploy_reason=BASELINE_ALREADY_PRESENT,
                sku_stats=None,
            )
        lines: list[MatrixDeployPayloadLine] = []
        incomplete = False
        is_first_run = not self.snapshot_store.has_unit_snapshot(
            machine_code=machine_code,
            logical_matrix_name=matrix.logical_matrix_name,
        )

        for cell in matrix.cells:
            snapshot_doc = self.snapshot_store.get_latest_line(
                machine_code=machine_code,
                logical_matrix_name=matrix.logical_matrix_name,
                line_number=cell.line_number,
            )
            snapshot_line = None
            has_baseline_line = False
            if snapshot_doc is not None:
                for record in snapshot_doc.lines:
                    if record.line_number == cell.line_number:
                        snapshot_line = _snapshot_line_from_record(record)
                        has_baseline_line = True
                        break

            decision = self._decide_product(
                machine_code=machine_code,
                logical_matrix_name=matrix.logical_matrix_name,
                line_number=cell.line_number,
                desired_product=cell.product_code,
                snapshot_line=snapshot_line,
            )
            effective_product = (
                decision.effective_product if decision is not None else cell.product_code
            )
            if effective_product is None:
                lines.append(
                    _blocked_empty_payload_line(cell.line_number, self.blocking_cell_price),
                )
                continue

            purchase = Decimal("0")
            capacity = 0
            purchase_valid = False
            capacity_valid = False
            catalog_entry: MatrixSkuCatalogEntry | None = None
            if self.sku_catalog_by_code is not None:
                catalog_entry = self.sku_catalog_by_code.get(effective_product)
                if catalog_entry is None or not is_matrix_ready(catalog_entry):
                    lines.append(
                        _blocked_empty_payload_line(cell.line_number, self.blocking_cell_price),
                    )
                    continue

            attrs_entry = self._lookup_purchase_attributes(effective_product)
            if catalog_entry is not None:
                if attrs_entry is not None:
                    purchase = Decimal(attrs_entry[0])
                    purchase_valid = purchase > 0
                capacity = catalog_entry.capacity
                capacity_valid = capacity > 0
                multiplier = catalog_entry.product_multiplier
                catalog_product_name = catalog_entry.display_name
            else:
                if attrs_entry is not None:
                    purchase_raw, capacity_raw = attrs_entry
                    purchase = Decimal(purchase_raw)
                    capacity = capacity_raw
                    purchase_valid = purchase > 0
                    capacity_valid = capacity > 0
                multiplier = self.product_multipliers.get(effective_product, Decimal("1"))
                catalog_product_name = cell.product_name

            calculated = Decimal(
                str(
                    calculate_sell_price(
                        purchase=purchase,
                        product_multiplier=multiplier,
                        matrix_multiplier=matrix.matrix_multiplier,
                        params=self.base_margin,
                    ),
                ),
            )
            merged = merge_sku_price(
                calculated_sell=calculated,
                purchase_valid=purchase_valid,
                capacity_valid=capacity_valid,
                catalog_product_code=effective_product,
                snapshot=snapshot_line,
                is_first_run=is_first_run,
                has_baseline_line=has_baseline_line,
                max_price_delta_pct=self.max_price_delta_pct,
            )

            if (
                (decision is None or not decision.blocked)
                and merged.outcome == "skipped_no_baseline"
                and (snapshot_line is None or snapshot_line.product_code != effective_product)
            ):
                incomplete = True

            if decision is not None and decision.blocked:
                assert snapshot_line is not None and decision.block_reason is not None
                use_snapshot = merged.outcome != "applied"
                blocked_deploy_price = snapshot_line.deploy_price if use_snapshot else calculated
                lines.append(
                    MatrixDeployPayloadLine(
                        line_number=cell.line_number,
                        product_code=effective_product,
                        product_name=snapshot_line.product_name,
                        deploy_price=blocked_deploy_price,
                        capacity=snapshot_line.capacity if use_snapshot else capacity,
                        outcome="product_swap_blocked",
                        reason=decision.block_reason,
                        strong_price_increase=False,
                        desired_product=cell.product_code,
                        baseline_price=None,
                        purchase_price=None if use_snapshot else purchase,
                        calculated_price=None if use_snapshot else calculated,
                    ),
                )
                continue

            deploy_price = merged.deploy_price or calculated
            product_name = catalog_product_name
            line_capacity = capacity
            if merged.outcome in {"kept_previous", "skipped_no_baseline"} and snapshot_line:
                product_name = snapshot_line.product_name
                line_capacity = snapshot_line.capacity
                deploy_price = snapshot_line.deploy_price

            lines.append(
                MatrixDeployPayloadLine(
                    line_number=cell.line_number,
                    product_code=effective_product,
                    product_name=product_name,
                    deploy_price=deploy_price,
                    capacity=line_capacity,
                    outcome=merged.outcome,
                    reason=merged.reason,
                    strong_price_increase=merged.strong_price_increase,
                    baseline_price=(
                        snapshot_line.deploy_price
                        if snapshot_line is not None and merged.strong_price_increase
                        else None
                    ),
                    purchase_price=purchase if merged.outcome == "applied" else None,
                    calculated_price=calculated if merged.outcome == "applied" else None,
                ),
            )

        if incomplete:
            built_lines = tuple(lines)
            return MatrixDeploySkippedUnit(
                logical_matrix_name=matrix.logical_matrix_name,
                machine_code=machine_code,
                deploy_status="skipped",
                deploy_reason=INCOMPLETE_MATRIX_NO_SNAPSHOT,
                sku_stats=sku_stats_from_lines(built_lines),
                lines=built_lines,
            )

        return MatrixDeployPayload(
            logical_matrix_name=matrix.logical_matrix_name,
            machine_code=machine_code,
            matrix_multiplier=str(matrix.matrix_multiplier),
            lines=tuple(lines),
        )
