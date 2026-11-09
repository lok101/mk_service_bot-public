from __future__ import annotations

from beartype import beartype

from src.application.machine_pnl.location_rent_sheet import (
    RowsLocationRentCatalog,
    parse_location_rent_sheet_rows,
)
from src.infrastructure.integrations.google.sheets.sheet_reader import read_sheet_rows


@beartype
def build_location_rent_catalog_from_rows(rows: list[list[str]]) -> RowsLocationRentCatalog:
    parsed = parse_location_rent_sheet_rows(rows)
    return RowsLocationRentCatalog(occupancies=parsed)


@beartype
def load_location_rent_sheet_rows(
    *,
    credentials_file: str,
    spreadsheet_id: str,
    sheet_id: int,
) -> list[list[str]]:
    return read_sheet_rows(
        credentials_file=credentials_file,
        spreadsheet_id=spreadsheet_id,
        sheet_id=sheet_id,
    )
