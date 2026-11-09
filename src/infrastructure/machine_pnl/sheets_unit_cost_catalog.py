from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.ports import UnitCostCatalog
from src.application.machine_pnl.unit_cost import UnitCostRow, effective_unit_cost
from src.application.machine_pnl.unit_cost_sheet import parse_unit_cost_sheet_rows
from src.infrastructure.integrations.google.sheets.sheet_reader import read_sheet_rows


@beartype
@dataclass(frozen=True, slots=True)
class RowsUnitCostCatalog:
    _rows: tuple[UnitCostRow, ...]

    @beartype
    def get(self, product_code: str, *, as_of: date) -> Decimal | None:
        return effective_unit_cost(self._rows, product_code=product_code, as_of=as_of)


@beartype
def build_unit_cost_catalog_from_rows(rows: list[list[str]]) -> UnitCostCatalog:
    parsed = parse_unit_cost_sheet_rows(rows)
    return RowsUnitCostCatalog(_rows=parsed)


@beartype
def load_unit_cost_sheet_rows(
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
