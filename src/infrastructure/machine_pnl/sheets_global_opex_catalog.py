from __future__ import annotations

from beartype import beartype

from src.application.machine_pnl.composed_opex_params import ComposedOpExParamsCatalog
from src.application.machine_pnl.global_opex_sheet import parse_global_opex_sheet_rows
from src.application.machine_pnl.opex_params import FixtureOpExParamsCatalog
from src.infrastructure.integrations.google.sheets.sheet_reader import read_sheet_rows


@beartype
def build_composed_opex_from_rows(
    rows: list[list[str]],
    *,
    machine: FixtureOpExParamsCatalog | None = None,
) -> ComposedOpExParamsCatalog:
    parsed = parse_global_opex_sheet_rows(rows)
    machine_catalog = FixtureOpExParamsCatalog.default() if machine is None else machine
    return ComposedOpExParamsCatalog(machine=machine_catalog, global_rows=parsed)


@beartype
def load_global_opex_sheet_rows(
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
