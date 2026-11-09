from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.provider import MatrixReferenceDataProvider
from src.application.matrix_automation.sheets.layout import (
    AUTO_SYNC_COL,
    BLOCK_COL_STEP,
    MACHINE_CODES_COL,
    MATRIX_MULTIPLIER_COL,
)
from src.application.reference_data import ReferenceDataSourceId

_HEADER_WIDTH = AUTO_SYNC_COL + 1


def make_provider() -> MatrixReferenceDataProvider:
    return MatrixReferenceDataProvider(
        product_multiplier_min=Decimal("0.8"),
        product_multiplier_max=Decimal("3.0"),
        matrix_multiplier_min=Decimal("0.8"),
        matrix_multiplier_max=Decimal("3.0"),
    )


_MS_NAME_TO_CODE: dict[str, str] = {"Кола 0.5": "MS-1"}


def seed_ms_name_to_code(provider: MatrixReferenceDataProvider) -> None:
    provider.set_name_to_code(dict(_MS_NAME_TO_CODE))


def catalog_tab(*, machines: str = "512") -> list[list[str]]:
    header = [""] * _HEADER_WIDTH
    header[MACHINE_CODES_COL] = machines
    header[MATRIX_MULTIPLIER_COL] = "1.0"
    header[AUTO_SYNC_COL] = "TRUE"
    width = max(_HEADER_WIDTH, BLOCK_COL_STEP + 1)
    product_row = [""] * width
    line_row = [""] * width
    product_row[0] = "Кола 0.5"
    line_row[0] = "1"
    line_row[BLOCK_COL_STEP] = "2"
    return [header, [], product_row, line_row]


class _NullUtilityStore:
    def get(self, source_id: ReferenceDataSourceId) -> None:
        return None


class UtilitySync:
    def __init__(self, provider: MatrixReferenceDataProvider) -> None:
        self._provider = provider
        self.store = _NullUtilityStore()
        self.rows_by_source = {
            ReferenceDataSourceId.PRODUCT_MULTIPLIERS: [
                ["product_code", "product_name", "multiplier"],
            ],
        }

    def sync_source(self, source_id: ReferenceDataSourceId) -> None:
        self._provider.apply_rows(source_id, self.rows_by_source[source_id])


class CatalogReader:
    def __init__(self, tabs: list[tuple[str, list[list[str]]]]) -> None:
        self._tabs = tabs

    def list_catalog_tabs(self) -> list[tuple[str, list[list[str]]]]:
        return self._tabs
