from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.application.machine_pnl.errors import LocationRentSheetError
from src.application.machine_pnl.location_rent_sheet import (
    RowsLocationRentCatalog,
    parse_location_rent_sheet_rows,
)
from src.domain.ids import MachineId

_HEADER = ["Сумма", "Процент", "Id локации", "Id ТТ", "Имя", "Дата установки", "Дата снятия"]


def test_location_rent_sheet_rejects_bad_header() -> None:
    with pytest.raises(LocationRentSheetError):
        parse_location_rent_sheet_rows([["sum", "pct", "loc", "tt", "name", "from", "to"]])


def test_location_rent_sheet_ignores_trailing_sheets_auto_columns() -> None:
    # edge: Google Sheets values.get returns unused grid cols as "Column N"
    header = [
        *_HEADER,
        "Column 8",
        "Column 9",
        "Column 10",
        "",
    ]
    rows = [
        header,
        ["100", "", "loc-1", "101", "A", "01.05.2026", "", "noise", ""],
    ]
    parsed = parse_location_rent_sheet_rows(rows)
    assert len(parsed) == 1
    assert parsed[0].location_id == "loc-1"
    assert parsed[0].machine_id == MachineId("101")
    assert parsed[0].rent_monthly == Decimal("100")


def test_location_rent_sheet_empty_sum_is_none_zero_kept() -> None:
    # edge: empty sum → None; "0" → Decimal("0"); empty % → None; ignore Имя
    rows = [
        _HEADER,
        ["", "2,5%", "loc-1", "101", "Ignored Name", "01.05.2026", ""],
        ["0", "", "loc-2", "101", "X", "01.06.2026", "15.06.2026"],
    ]
    parsed = parse_location_rent_sheet_rows(rows)
    assert parsed[0].rent_monthly is None
    assert parsed[0].rent_percent == Decimal("2.5")
    assert parsed[0].location_id == "loc-1"
    assert parsed[0].machine_id == MachineId("101")
    assert parsed[0].installed_at == datetime(2026, 5, 1, tzinfo=UTC)
    assert parsed[0].removed_at is None
    assert parsed[1].rent_monthly == Decimal("0")
    assert parsed[1].rent_percent is None
    assert parsed[1].removed_at == datetime(2026, 6, 15, tzinfo=UTC)


def test_location_rent_sheet_bad_date_fail_closed() -> None:
    with pytest.raises(LocationRentSheetError):
        parse_location_rent_sheet_rows([_HEADER, ["100", "", "loc", "101", "n", "bad-date", ""]])


def test_rows_location_rent_catalog_filters_by_machine() -> None:
    rows = [
        _HEADER,
        ["100", "", "loc-1", "101", "A", "01.05.2026", ""],
        ["200", "", "loc-2", "202", "B", "01.06.2026", ""],
    ]
    catalog = RowsLocationRentCatalog(occupancies=parse_location_rent_sheet_rows(rows))
    only_101 = catalog.list_for_machine(MachineId("101"))
    assert len(only_101) == 1
    assert only_101[0].location_id == "loc-1"
    assert catalog.list_for_machine(MachineId("999")) == ()
