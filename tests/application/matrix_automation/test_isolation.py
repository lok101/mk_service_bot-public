from __future__ import annotations

from decimal import Decimal

from tests.application.matrix_automation.fixtures.curved_margin_params import (
    curved_margin_params,
)

from src.application.matrix_automation.build_deploy_payloads import BuildMatrixDeployPayloads
from src.application.matrix_automation.models import (
    BlockedMatrixEntry,
    EnabledLogicalMatrix,
    MatrixCatalogCell,
    MatrixParseState,
    PriceSnapshotDocument,
    ProductBlock,
    PurchaseAttributesFetchResult,
)


class _PurchaseReader:
    def fetch_attributes(
        self,
        product_codes: frozenset[str],
    ) -> PurchaseAttributesFetchResult:
        attributes = {code: ("10.00", 12) for code in product_codes}
        return PurchaseAttributesFetchResult(
            attributes=attributes,
            cards_found=len(attributes),
        )


class _SnapshotStore:
    def has_unit_snapshot(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
    ) -> bool:
        return False

    def get_latest_line(
        self,
        *,
        machine_code: str,
        logical_matrix_name: str,
        line_number: int,
    ) -> None:
        return None

    def list_latest_for_machine(
        self,
        *,
        machine_code: str,
    ) -> tuple[PriceSnapshotDocument, ...]:
        return ()

    def save(self, document: object) -> None:
        return None


def test_product_level_block_skips_only_affected_matrix() -> None:
    state = MatrixParseState(
        enabled_matrices=(
            EnabledLogicalMatrix(
                logical_matrix_name="Snacks",
                machine_codes=("512",),
                matrix_multiplier=Decimal("1.0"),
                cells=(MatrixCatalogCell(1, "Кола 0.5", "MS-1"),),
            ),
            EnabledLogicalMatrix(
                logical_matrix_name="Drinks",
                machine_codes=("777",),
                matrix_multiplier=Decimal("1.0"),
                cells=(MatrixCatalogCell(1, "Water", "MS-2"),),
            ),
        ),
        blocked_matrices=(
            BlockedMatrixEntry(
                logical_matrix_name="Snacks",
                deploy_reason="product_reference_invalid",
                detail="moysklad_fetch_failed: MS-1",
                products=(),
                machine_codes=("512",),
            ),
        ),
        product_block_map={
            "MS-1": ProductBlock(
                product_name="Кола 0.5",
                product_code="MS-1",
                detail="moysklad_fetch_failed: MS-1",
            ),
        },
        auto_sync_disabled_matrices=0,
    )
    builder = BuildMatrixDeployPayloads(
        snapshot_store=_SnapshotStore(),
        purchase_reader=_PurchaseReader(),
        blocking_cell_price=Decimal("999"),
        max_price_delta_pct=Decimal("30"),
        base_margin=curved_margin_params(),
        product_multipliers={"MS-1": Decimal("1"), "MS-2": Decimal("1")},
        purchase_attributes={"MS-2": ("10.00", 12)},
    )
    result = builder(state)
    assert len(result.payloads) == 1
    assert result.payloads[0].logical_matrix_name == "Drinks"
    assert len(result.skipped_units) == 1
    assert result.skipped_units[0].logical_matrix_name == "Snacks"
