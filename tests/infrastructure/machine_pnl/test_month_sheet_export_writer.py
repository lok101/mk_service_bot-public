from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from src.application.machine_pnl.models import PnlWarning
from src.application.machine_pnl.month_models import MonthPnlSnapshot
from src.application.machine_pnl.opex_breakdown import empty_opex_breakdown
from src.domain.ids import MachineId
from src.infrastructure.machine_pnl.month_sheet_export_writer import (
    MONTH_PNL_SHEET_HEADERS,
    MonthPnlSheetExportWriter,
)

_SHEET_TITLE = "MonthPnl"
_REVENUE_INDEX = MONTH_PNL_SHEET_HEADERS.index("revenue")


@pytest.fixture(autouse=True)
def _stub_sheets_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = MagicMock()
    monkeypatch.setattr(
        "src.infrastructure.machine_pnl.month_sheet_export_writer._get_rate_limiter",
        lambda: limiter,
    )


def test_month_sheet_export_writer_acquires_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = MagicMock()
    monkeypatch.setattr(
        "src.infrastructure.machine_pnl.month_sheet_export_writer._get_rate_limiter",
        lambda: limiter,
    )
    writer = MonthPnlSheetExportWriter(
        service_factory=lambda: (_ for _ in ()).throw(AssertionError("no api")),
        spreadsheet_id="sid",
        sheet_id=1,
        tz=ZoneInfo("UTC"),
    )
    with pytest.raises(AssertionError):
        writer.ensure_header(["a"])
    limiter.acquire.assert_called()


def _snap(*, revenue: str = "10.00") -> MonthPnlSnapshot:
    return MonthPnlSnapshot(
        machine_id=MachineId("101"),
        location_id="loc-a",
        technician_id="tech-1",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        revenue=Decimal(revenue),
        revenue_known_as_of=date(2026, 6, 30),
        cogs_expected=Decimal("4.00"),
        cogs_actual_fact=Decimal("5.00"),
        cogs_actual_estimate=Decimal("0.00"),
        allocated_shortage_fact=Decimal("1.00"),
        allocated_shortage_estimate=Decimal("0.00"),
        allocated_surplus_fact=Decimal("0.00"),
        allocated_surplus_estimate=Decimal("0.00"),
        opex_breakdown=empty_opex_breakdown(),
        opex_known_total=Decimal("2.00"),
        net_theory=Decimal("4.00"),
        machine_gap=Decimal("1.00"),
        net_machine=Decimal("3.00"),
        tech_gap=Decimal("1.00"),
        net_after_tech=Decimal("2.00"),
        coverage_days=30,
        days_in_month=30,
        coverage_pct=Decimal("100"),
        projection_basis="fact",
        warnings=(PnlWarning(code="x", message="m"),),
        last_recomputed_at=datetime(2026, 7, 1, tzinfo=UTC),
    )


class _Grid:
    def __init__(self) -> None:
        self.rows: list[list[str]] = []

    def data_row_count(self) -> int:
        if not self.rows:
            return 0
        return max(0, len(self.rows) - 1)

    def row(self, i: int) -> list[str]:
        return self.rows[i]


def _apply_values_at_row(grid: _Grid, start_row: int, values: list[list[str]]) -> None:
    start = start_row - 1
    while len(grid.rows) < start:
        grid.rows.append([])
    for offset, row in enumerate(values):
        idx = start + offset
        if idx < len(grid.rows):
            grid.rows[idx] = list(row)
        else:
            grid.rows.append(list(row))


def _row_number_from_a1(range_name: str) -> int:
    _, _, cell = range_name.partition("!")
    cell = cell.split(":")[0].replace("$", "")
    digits = "".join(ch for ch in cell if ch.isdigit())
    return int(digits) if digits else 1


class _ValuesApi:
    def __init__(self, grid: _Grid, recorder: dict[str, Any]) -> None:
        self._grid = grid
        self._recorder = recorder

    def get(self, **kwargs: object) -> Any:
        self._recorder.setdefault("gets", []).append(kwargs)

        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                if not self._grid.rows:
                    return {"values": []}
                return {"values": [list(row) for row in self._grid.rows]}

        return _Exec()

    def append(self, **kwargs: object) -> Any:
        self._recorder.setdefault("appends", []).append(kwargs)
        body = kwargs.get("body")
        values: list[list[str]] = []
        if isinstance(body, dict):
            raw = body.get("values")
            if isinstance(raw, list):
                values = [list(row) for row in raw]

        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                self._grid.rows.extend(values)
                return {}

        return _Exec()

    def update(self, **kwargs: object) -> Any:
        self._recorder.setdefault("updates", []).append(kwargs)
        body = kwargs.get("body")
        start_row = _row_number_from_a1(str(kwargs.get("range", "")))
        values: list[list[str]] = []
        if isinstance(body, dict):
            raw = body.get("values")
            if isinstance(raw, list):
                values = [list(row) for row in raw]

        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                _apply_values_at_row(self._grid, start_row, values)
                return {}

        return _Exec()

    def batchUpdate(self, **kwargs: object) -> Any:
        self._recorder.setdefault("value_batch_updates", []).append(kwargs)
        body = kwargs.get("body")
        items: list[object] = []
        if isinstance(body, dict):
            raw = body.get("data")
            if isinstance(raw, list):
                items = list(raw)

        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    start_row = _row_number_from_a1(str(item.get("range", "")))
                    raw_values = item.get("values")
                    values: list[list[str]] = []
                    if isinstance(raw_values, list):
                        values = [list(row) for row in raw_values if isinstance(row, list)]
                    _apply_values_at_row(self._grid, start_row, values)
                return {}

        return _Exec()


class _Spreadsheets:
    def __init__(self, grid: _Grid, recorder: dict[str, Any]) -> None:
        self._grid = grid
        self._recorder = recorder

    def values(self) -> _ValuesApi:
        return _ValuesApi(self._grid, self._recorder)

    def get(self, **kwargs: object) -> Any:
        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                return {
                    "sheets": [
                        {"properties": {"sheetId": 9, "title": _SHEET_TITLE}},
                    ]
                }

        return _Exec()


class _Service:
    def __init__(self, grid: _Grid, recorder: dict[str, Any]) -> None:
        self._grid = grid
        self._recorder = recorder

    def spreadsheets(self) -> _Spreadsheets:
        return _Spreadsheets(self._grid, self._recorder)

    def close(self) -> None:
        return None


def _fake_writer(
    *,
    location_display_lookup: Callable[[str], str] | None = None,
    technician_name_lookup: Callable[[str], str] | None = None,
    company_name_lookup: Callable[[int], str] | None = None,
) -> tuple[MonthPnlSheetExportWriter, _Grid, dict[str, Any]]:
    grid = _Grid()
    recorder: dict[str, Any] = {}
    writer = MonthPnlSheetExportWriter(
        service_factory=lambda: _Service(grid, recorder),
        spreadsheet_id="ssid",
        sheet_id=9,
        tz=ZoneInfo("Europe/Moscow"),
        sleep=lambda _s: None,
        location_display_lookup=location_display_lookup,
        technician_name_lookup=technician_name_lookup,
        company_name_lookup=company_name_lookup,
    )
    return writer, grid, recorder


def test_sheets_upsert_updates_existing_row_in_place() -> None:
    writer, grid, _recorder = _fake_writer()
    writer.ensure_header(MONTH_PNL_SHEET_HEADERS)
    writer.upsert_rows((_snap(revenue="10.00"),))
    writer.upsert_rows((_snap(revenue="20.00"),))
    assert grid.data_row_count() == 1
    revenue_cell = grid.row(1)[_REVENUE_INDEX]
    assert "20" in revenue_cell or revenue_cell == "20"


def test_sheets_upsert_appends_new_key_at_end() -> None:
    writer, grid, _recorder = _fake_writer()
    writer.ensure_header(MONTH_PNL_SHEET_HEADERS)
    first = _snap(revenue="1.00")
    second = replace(_snap(revenue="2.00"), machine_id=MachineId("102"))
    writer.upsert_rows((first,))
    writer.upsert_rows((second,))
    assert grid.data_row_count() == 2
    assert grid.row(1)[0] == "101"
    assert grid.row(2)[0] == "102"


def test_sheets_row_uses_format_sheet_decimal() -> None:
    writer, grid, _recorder = _fake_writer()
    writer.ensure_header(MONTH_PNL_SHEET_HEADERS)
    writer.upsert_rows((_snap(revenue="12.5"),))
    assert grid.row(1)[_REVENUE_INDEX] == "12,5"
    assert grid.row(1)[_REVENUE_INDEX] != "12.5"


def test_sheets_upsert_writes_new_keys_via_update_at_next_data_row() -> None:
    writer, grid, recorder = _fake_writer()
    writer.ensure_header(MONTH_PNL_SHEET_HEADERS)
    recorder.clear()
    first = _snap(revenue="1.00")
    second = replace(_snap(revenue="2.00"), machine_id=MachineId("102"))
    writer.upsert_rows((first, second))
    assert recorder.get("appends", []) == []
    updates = recorder.get("updates", [])
    header_updates = [item for item in updates if str(item["range"]).endswith("!A1")]
    data_updates = [item for item in updates if not str(item["range"]).endswith("!A1")]
    assert len(header_updates) == 0
    assert len(data_updates) == 1
    assert str(data_updates[0]["range"]).endswith("!A2")
    body = data_updates[0]["body"]
    assert isinstance(body, dict)
    rows = body["values"]
    assert isinstance(rows, list)
    assert len(rows) == 2
    assert grid.data_row_count() == 2


def test_sheets_upsert_writes_missing_keys_after_existing_subset() -> None:
    writer, grid, recorder = _fake_writer()
    writer.ensure_header(MONTH_PNL_SHEET_HEADERS)
    existing = _snap(revenue="1.00")
    missing = replace(_snap(revenue="2.00"), machine_id=MachineId("102"))
    writer.upsert_rows((existing,))
    recorder.clear()
    writer.upsert_rows((existing, missing))
    assert recorder.get("appends", []) == []
    batches = recorder.get("value_batch_updates", [])
    assert len(batches) == 1
    updates = recorder.get("updates", [])
    header_updates = [item for item in updates if str(item["range"]).endswith("!A1")]
    data_updates = [item for item in updates if not str(item["range"]).endswith("!A1")]
    assert len(header_updates) == 0
    assert len(data_updates) == 1
    assert str(data_updates[0]["range"]).endswith("!A3")
    body = data_updates[0]["body"]
    assert isinstance(body, dict)
    rows = body["values"]
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert grid.data_row_count() == 2
    assert grid.row(1)[0] == "101"
    assert grid.row(2)[0] == "102"


def test_sheets_upsert_updates_existing_rows_in_one_batch() -> None:
    writer, grid, recorder = _fake_writer()
    writer.ensure_header(MONTH_PNL_SHEET_HEADERS)
    first = _snap(revenue="1.00")
    second = replace(_snap(revenue="2.00"), machine_id=MachineId("102"))
    writer.upsert_rows((first, second))
    recorder.clear()
    writer.upsert_rows(
        (
            _snap(revenue="11.00"),
            replace(_snap(revenue="22.00"), machine_id=MachineId("102")),
        )
    )
    assert recorder.get("appends", []) == []
    batches = recorder.get("value_batch_updates", [])
    assert len(batches) == 1
    body = batches[0]["body"]
    assert isinstance(body, dict)
    data = body["data"]
    assert isinstance(data, list)
    assert len(data) == 2
    assert grid.data_row_count() == 2
    assert "11" in grid.row(1)[_REVENUE_INDEX]
    assert "22" in grid.row(2)[_REVENUE_INDEX]


def test_month_pnl_headers_insert_company_columns() -> None:
    headers = list(MONTH_PNL_SHEET_HEADERS)
    assert headers[0:9] == [
        "machine_id",
        "location_name",
        "technician_name",
        "company_name",
        "location_id",
        "company_id",
        "technician_id",
        "period_start",
        "period_end",
    ]
    assert "latitude" not in headers
    assert "longitude" not in headers


def test_upsert_fills_location_display_from_lookup() -> None:
    def lookup(location_id: str) -> str:
        if location_id == "loc-a":
            return "Кафе А"
        return ""

    writer, grid, _recorder = _fake_writer(location_display_lookup=lookup)
    writer.upsert_rows((_snap(),))
    headers = MONTH_PNL_SHEET_HEADERS
    assert grid.row(1)[headers.index("location_name")] == "Кафе А"


def test_upsert_empty_location_display_when_unknown() -> None:
    def lookup(location_id: str) -> str:
        return ""

    writer, grid, _recorder = _fake_writer(location_display_lookup=lookup)
    writer.upsert_rows((_snap(),))
    headers = MONTH_PNL_SHEET_HEADERS
    assert grid.row(1)[headers.index("location_name")] == ""


def test_upsert_fills_technician_name_from_lookup() -> None:
    def lookup(technician_id: str) -> str:
        return "Данил" if technician_id == "tech-1" else ""

    writer, grid, _recorder = _fake_writer(technician_name_lookup=lookup)
    writer.upsert_rows((_snap(),))
    assert grid.row(1)[MONTH_PNL_SHEET_HEADERS.index("technician_name")] == "Данил"


def test_upsert_empty_location_display_when_snapshot_id_missing() -> None:
    def lookup(location_id: str) -> str:
        raise AssertionError("lookup must not run for empty location_id")

    writer, grid, _recorder = _fake_writer(location_display_lookup=lookup)
    writer.upsert_rows((replace(_snap(), location_id=None),))
    headers = MONTH_PNL_SHEET_HEADERS
    assert grid.row(1)[headers.index("location_name")] == ""


def test_upsert_empty_technician_name_when_id_missing() -> None:
    def lookup(technician_id: str) -> str:
        raise AssertionError("lookup must not run for empty technician_id")

    writer, grid, _recorder = _fake_writer(technician_name_lookup=lookup)
    writer.upsert_rows((replace(_snap(), technician_id=None),))
    assert grid.row(1)[MONTH_PNL_SHEET_HEADERS.index("technician_name")] == ""


def test_upsert_looks_up_by_location_id_not_latest_machine() -> None:
    def lookup(location_id: str) -> str:
        mapping = {
            "loc-old": "Старая",
            "loc-new": "Новая",
        }
        return mapping.get(location_id, "")

    writer, grid, _recorder = _fake_writer(location_display_lookup=lookup)
    writer.upsert_rows((replace(_snap(), location_id="loc-old"),))
    assert grid.row(1)[MONTH_PNL_SHEET_HEADERS.index("location_name")] == "Старая"


_LEGACY_MONTH_PNL_SHEET_HEADERS: tuple[str, ...] = (
    "machine_id",
    "location_id",
    "technician_id",
    "period_start",
    "period_end",
    "revenue",
    "revenue_known_as_of",
    "cogs_expected",
    "cogs_actual_fact",
    "cogs_actual_estimate",
    "allocated_shortage_fact",
    "allocated_shortage_estimate",
    "allocated_surplus_fact",
    "allocated_surplus_estimate",
    "rent_fixed",
    "rent_percent",
    "terminal",
    "labor",
    "acquiring_percent",
    "acquiring_per_sale",
    "opex_known_total",
    "net_theory",
    "machine_gap",
    "net_machine",
    "tech_gap",
    "net_after_tech",
    "coverage_days",
    "days_in_month",
    "coverage_pct",
    "projection_basis",
    "warnings",
    "last_recomputed_at",
)


def test_upsert_preserves_header_when_a1_filled() -> None:
    writer, grid, _recorder = _fake_writer()
    renamed = list(MONTH_PNL_SHEET_HEADERS)
    renamed[MONTH_PNL_SHEET_HEADERS.index("location_name")] = "Имя точки"
    grid.rows = [renamed]
    writer.upsert_rows((_snap(),))
    assert grid.row(0)[MONTH_PNL_SHEET_HEADERS.index("location_name")] == "Имя точки"


def test_upsert_preserves_legacy_headers_and_updates_data_row() -> None:
    def lookup(location_id: str) -> str:
        if location_id == "loc-a":
            return "Кафе А"
        return ""

    writer, grid, _recorder = _fake_writer(location_display_lookup=lookup)
    legacy_row = [""] * len(_LEGACY_MONTH_PNL_SHEET_HEADERS)
    legacy_row[0] = "101"
    legacy_row[1] = "loc-a"
    legacy_row[2] = "tech-1"
    legacy_row[3] = "01.06.2026"
    legacy_headers = list(_LEGACY_MONTH_PNL_SHEET_HEADERS)
    grid.rows = [legacy_headers, legacy_row]
    writer.upsert_rows((_snap(),))
    assert list(grid.row(0)) == legacy_headers
    assert grid.row(1)[MONTH_PNL_SHEET_HEADERS.index("location_name")] == "Кафе А"


def test_upsert_writes_header_when_sheet_empty() -> None:
    writer, grid, _recorder = _fake_writer()
    assert grid.data_row_count() == 0
    writer.upsert_rows((_snap(),))
    assert list(grid.row(0))[: len(MONTH_PNL_SHEET_HEADERS)] == list(MONTH_PNL_SHEET_HEADERS)
    assert grid.data_row_count() == 1


def test_upsert_fills_company_id_and_name() -> None:
    def lookup(company_id: int) -> str:
        return "Орлов М.О." if company_id == 42 else ""

    writer, grid, _recorder = _fake_writer(company_name_lookup=lookup)
    writer.upsert_rows((replace(_snap(), company_id=42),))
    headers = MONTH_PNL_SHEET_HEADERS
    assert grid.row(1)[headers.index("company_id")] == "42"
    assert grid.row(1)[headers.index("company_name")] == "Орлов М.О."


def test_upsert_company_id_is_plain_int_string() -> None:
    writer, grid, _recorder = _fake_writer()
    writer.upsert_rows((replace(_snap(), company_id=1001),))
    cell = grid.row(1)[MONTH_PNL_SHEET_HEADERS.index("company_id")]
    assert cell == "1001"
    assert "," not in cell
    assert " " not in cell


def test_upsert_empty_company_cells_when_snapshot_id_missing() -> None:
    def lookup(company_id: int) -> str:
        raise AssertionError("lookup must not run when company_id is None")

    writer, grid, _recorder = _fake_writer(company_name_lookup=lookup)
    writer.upsert_rows((replace(_snap(), company_id=None),))
    headers = MONTH_PNL_SHEET_HEADERS
    assert grid.row(1)[headers.index("company_id")] == ""
    assert grid.row(1)[headers.index("company_name")] == ""
    assert grid.row(1)[headers.index("machine_id")] == "101"


def test_upsert_empty_company_name_when_unknown() -> None:
    def lookup(company_id: int) -> str:
        return ""

    writer, grid, _recorder = _fake_writer(company_name_lookup=lookup)
    writer.upsert_rows((replace(_snap(), company_id=42),))
    assert grid.row(1)[MONTH_PNL_SHEET_HEADERS.index("company_id")] == "42"
    assert grid.row(1)[MONTH_PNL_SHEET_HEADERS.index("company_name")] == ""


def test_upsert_row_does_not_contain_account_secrets() -> None:
    def lookup(company_id: int) -> str:
        return "Орлов М.О."

    writer, grid, _recorder = _fake_writer(company_name_lookup=lookup)
    writer.upsert_rows((replace(_snap(), company_id=42),))
    joined = "|".join(grid.row(1))
    assert "secret" not in joined.lower()
    assert "password" not in joined.lower()
    assert "login" not in joined.lower()


def test_month_snapshot_has_no_display_fields() -> None:
    fields = MonthPnlSnapshot.__dataclass_fields__
    assert "location_name" not in fields
    assert "latitude" not in fields
    assert "longitude" not in fields
    assert "technician_name" not in fields
    assert "company_name" not in fields
    assert "company_id" in fields
    assert "location_id" in fields
    assert "technician_id" in fields
