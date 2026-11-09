from __future__ import annotations

from src.config.matrix_automation import MatrixAutomationSettings
from src.infrastructure.composition.matrix_automation_factory import (
    build_matrix_reference_data_source_map,
)
from src.infrastructure.composition.wiring.provider_backed_run_build import (
    ProviderBackedRunMatrixDeployBuild,
)


def test_provider_backed_build_has_sku_catalog_fields() -> None:
    fields = set(ProviderBackedRunMatrixDeployBuild.__dataclass_fields__)
    assert "sku_catalog_master_enabled" in fields
    assert "sku_catalog_store" in fields


def test_source_map_skips_multipliers_when_sku_catalog_master_enabled() -> None:
    """Flag on: do NOT assert product_multipliers_sheet_id; PRODUCT_MULTIPLIERS absent."""
    from src.application.reference_data import ReferenceDataSourceId

    settings = MatrixAutomationSettings.model_construct(
        google_sheets_spreadsheet_id="sheet-id",
        product_multipliers_sheet_id=None,
    )
    source_map = build_matrix_reference_data_source_map(
        settings,
        sku_catalog_master_enabled=True,
    )

    assert source_map == {}
    assert ReferenceDataSourceId.PRODUCT_MULTIPLIERS not in source_map
