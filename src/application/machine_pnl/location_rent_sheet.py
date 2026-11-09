from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from beartype import beartype

from src.application.machine_pnl.errors import LocationRentSheetError
from src.application.machine_pnl.rent_slices import LocationRentOccupancy
from src.application.shared.sheet_cell_format import parse_sheet_date, parse_sheet_decimal
from src.application.shared.sheet_rows import sheet_header_matches_canonical
from src.domain.ids import MachineId

_CANONICAL_HEADER = (
    "Сумма",
    "Процент",
    "Id локации",
    "Id ТТ",
    "Имя",
    "Дата установки",
    "Дата снятия",
)


@beartype
@dataclass(frozen=True, slots=True)
class RowsLocationRentCatalog:
    occupancies: tuple[LocationRentOccupancy, ...]

    @beartype
    def list_for_machine(self, machine_id: MachineId) -> tuple[LocationRentOccupancy, ...]:
        return tuple(row for row in self.occupancies if row.machine_id == machine_id)


@beartype
def parse_location_rent_sheet_rows(rows: list[list[str]]) -> tuple[LocationRentOccupancy, ...]:
    if not rows:
        raise LocationRentSheetError("location rent sheet is empty")
    header = tuple(cell.strip() for cell in rows[0])
    if not sheet_header_matches_canonical(header, _CANONICAL_HEADER):
        raise LocationRentSheetError(
            f"location rent header must be {_CANONICAL_HEADER}, got {header}"
        )
    parsed: list[LocationRentOccupancy] = []
    for row in rows[1:]:
        if _is_empty_row(row):
            continue
        parsed.append(_parse_location_rent_data_row(row))
    return tuple(parsed)


@beartype
def _is_empty_row(row: list[str]) -> bool:
    return all(not cell.strip() for cell in row)


@beartype
def _cell(row: list[str], index: int) -> str:
    if index >= len(row):
        return ""
    return row[index].strip()


@beartype
def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


@beartype
def _parse_optional_decimal(raw: str, *, field: str) -> Decimal | None:
    if not raw:
        return None
    try:
        return parse_sheet_decimal(raw)
    except ValueError as exc:
        raise LocationRentSheetError(f"invalid {field}: {raw!r}") from exc


@beartype
def _parse_required_date(raw: str, *, field: str) -> date:
    if not raw:
        raise LocationRentSheetError(f"{field} missing on non-empty location rent row")
    try:
        return parse_sheet_date(raw)
    except ValueError as exc:
        raise LocationRentSheetError(f"invalid {field}: {raw!r}") from exc


@beartype
def _parse_location_rent_data_row(row: list[str]) -> LocationRentOccupancy:
    rent_monthly_raw = _cell(row, 0)
    rent_percent_raw = _cell(row, 1)
    location_id = _cell(row, 2)
    machine_id_raw = _cell(row, 3)
    # column «Имя» (index 4) ignored
    installed_raw = _cell(row, 5)
    removed_raw = _cell(row, 6)

    if not location_id:
        raise LocationRentSheetError("location_id missing on non-empty location rent row")
    if not machine_id_raw:
        raise LocationRentSheetError("machine_id missing on non-empty location rent row")

    installed_at = _date_to_utc_midnight(_parse_required_date(installed_raw, field="installed_at"))
    removed_at: datetime | None
    if not removed_raw:
        removed_at = None
    else:
        removed_at = _date_to_utc_midnight(_parse_required_date(removed_raw, field="removed_at"))

    return LocationRentOccupancy(
        location_id=location_id,
        machine_id=MachineId(machine_id_raw),
        installed_at=installed_at,
        removed_at=removed_at,
        rent_monthly=_parse_optional_decimal(rent_monthly_raw, field="rent_monthly"),
        rent_percent=_parse_optional_decimal(rent_percent_raw, field="rent_percent"),
    )
