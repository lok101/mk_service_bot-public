from __future__ import annotations

from src.application.reference_data import ReferenceDataSourceId
from src.config.matrix_automation import MatrixAutomationSettings
from src.infrastructure.composition.matrix_automation_factory import (
    build_matrix_reference_data_source_map,
)
from src.infrastructure.matrix_automation.sheets_reader import list_worksheet_titles


def test_list_worksheet_titles_excludes_utility_sheet_ids() -> None:
    metadata = {
        "sheets": [
            {"properties": {"sheetId": 3, "title": "product_multipliers"}},
            {"properties": {"sheetId": 4, "title": "price_stream"}},
            {"properties": {"sheetId": 100, "title": "Snacks"}},
            {"properties": {"sheetId": 101, "title": "Drinks"}},
        ],
    }
    titles = list_worksheet_titles(
        spreadsheet_metadata=metadata,
        exclude_sheet_ids={3, 4},
    )
    assert titles == ["Snacks", "Drinks"]


def test_build_matrix_reference_data_source_map_has_multipliers_only() -> None:
    settings = MatrixAutomationSettings.model_construct(
        google_sheets_spreadsheet_id="sheet-1",
        product_multipliers_sheet_id=3,
    )
    source_map = build_matrix_reference_data_source_map(settings)
    assert set(source_map) == {ReferenceDataSourceId.PRODUCT_MULTIPLIERS}
    assert source_map[ReferenceDataSourceId.PRODUCT_MULTIPLIERS] == ("sheet-1", 3)
