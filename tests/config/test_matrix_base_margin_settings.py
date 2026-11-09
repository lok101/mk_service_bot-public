from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.matrix_automation import MatrixAutomationSettings
from src.config.mongodb import MongoSettings


def test_matrix_base_margin_collection_default() -> None:
    assert MongoSettings().matrix_base_margin_collection == "matrix_base_margin"


def test_matrix_base_margin_collection_rejects_blank() -> None:
    with pytest.raises(ValidationError):
        MongoSettings(matrix_base_margin_collection="  ")


def test_matrix_settings_has_no_base_margin_sheet_id() -> None:
    assert not hasattr(MatrixAutomationSettings(), "base_margin_sheet_id")


def test_spreadsheet_no_longer_requires_base_margin_gid() -> None:
    s = MatrixAutomationSettings(
        google_sheets_spreadsheet_id="sheet",
        product_multipliers_sheet_id=1,
    )
    assert s.google_sheets_spreadsheet_id == "sheet"
    assert s.product_multipliers_sheet_id == 1


def test_matrix_settings_has_no_price_change_stream_sheet_id() -> None:
    assert not hasattr(MatrixAutomationSettings(), "price_change_stream_sheet_id")
