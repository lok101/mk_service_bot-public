from __future__ import annotations

from collections.abc import Callable
from typing import Any

from beartype import beartype

SheetMetadata = dict[str, Any]


@beartype
def list_worksheet_titles(
    *,
    spreadsheet_metadata: SheetMetadata,
    exclude_sheet_ids: set[int],
) -> list[str]:
    raw_sheets = spreadsheet_metadata.get("sheets", [])
    if not isinstance(raw_sheets, list):
        raise ValueError("Spreadsheet sheets must be a list")
    titles: list[str] = []
    for raw_sheet in raw_sheets:
        if not isinstance(raw_sheet, dict):
            continue
        raw_properties = raw_sheet.get("properties")
        if not isinstance(raw_properties, dict):
            continue
        raw_sheet_id = raw_properties.get("sheetId")
        raw_title = raw_properties.get("title")
        if raw_sheet_id in exclude_sheet_ids:
            continue
        if isinstance(raw_title, str) and raw_title:
            titles.append(raw_title)
    return titles


@beartype
def read_sheet_rows_by_title(
    *,
    sheet_values: list[list[Any]],
) -> list[list[str]]:
    rows = [row for row in sheet_values if isinstance(row, list)]
    return [[str(cell) for cell in row] for row in rows]


@beartype
class MatrixCatalogSheetsReader:
    def __init__(
        self,
        *,
        credentials_file: str,
        spreadsheet_id: str,
        exclude_sheet_ids: set[int],
        fetch_metadata: Callable[[], SheetMetadata] | None = None,
        fetch_values_by_title: Callable[[str], list[list[Any]]] | None = None,
    ) -> None:
        self._credentials_file = credentials_file
        self._spreadsheet_id = spreadsheet_id
        self._exclude_sheet_ids = exclude_sheet_ids
        self._fetch_metadata = fetch_metadata
        self._fetch_values_by_title = fetch_values_by_title

    @beartype
    def list_catalog_tab_titles(self) -> list[str]:
        metadata = self._load_metadata()
        return list_worksheet_titles(
            spreadsheet_metadata=metadata,
            exclude_sheet_ids=self._exclude_sheet_ids,
        )

    @beartype
    def read_catalog_tab(self, title: str) -> list[list[str]]:
        if self._fetch_values_by_title is None:
            msg = "fetch_values_by_title is not configured"
            raise RuntimeError(msg)
        return read_sheet_rows_by_title(sheet_values=self._fetch_values_by_title(title))

    @beartype
    def list_catalog_tabs(self) -> list[tuple[str, list[list[str]]]]:
        return [(title, self.read_catalog_tab(title)) for title in self.list_catalog_tab_titles()]

    @beartype
    def _load_metadata(self) -> SheetMetadata:
        if self._fetch_metadata is None:
            msg = "fetch_metadata is not configured"
            raise RuntimeError(msg)
        return self._fetch_metadata()
