from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.event_reminders.sheets_source import GoogleSheetsEventSource

_HEADER = ["Дата", "Локация", "Комментарий"]
_DATA_ROW = ["29.07.2026", "A", "c"]


def test_sheet_reader_returns_header_and_str_cells() -> None:
    """Happy: returns formatted A–C rows including header; cells are str."""

    def resolve_title(*, spreadsheet_id: str, sheet_id: int) -> str:
        assert spreadsheet_id == "sheet-id"
        assert sheet_id == 42
        return "Events"

    def fetch_values(*, sheet_title: str, range_a1: str) -> list[list[Any]]:
        assert sheet_title == "Events"
        return [_HEADER, _DATA_ROW]

    source = GoogleSheetsEventSource(
        credentials_file="unused.json",
        spreadsheet_id="sheet-id",
        sheet_id=42,
        resolve_title=resolve_title,
        fetch_values=fetch_values,
    )

    rows = source.read_event_rows()

    assert rows == [_HEADER, _DATA_ROW]
    assert all(isinstance(cell, str) for row in rows for cell in row)


def test_sheet_reader_resolves_gid_to_title_and_range() -> None:
    """Happy: gid → title → values.get uses '{title}'!A:C."""
    captured: dict[str, object] = {}

    def resolve_title(*, spreadsheet_id: str, sheet_id: int) -> str:
        captured["spreadsheet_id"] = spreadsheet_id
        captured["sheet_id"] = sheet_id
        return "My Sheet"

    def fetch_values(*, sheet_title: str, range_a1: str) -> list[list[Any]]:
        captured["sheet_title"] = sheet_title
        captured["range_a1"] = range_a1
        return [[1, 2, 3]]

    source = GoogleSheetsEventSource(
        credentials_file="creds.json",
        spreadsheet_id="ss-id",
        sheet_id=7,
        resolve_title=resolve_title,
        fetch_values=fetch_values,
    )

    rows = source.read_event_rows()

    assert captured == {
        "spreadsheet_id": "ss-id",
        "sheet_id": 7,
        "sheet_title": "My Sheet",
        "range_a1": "'My Sheet'!A:C",
    }
    assert rows == [["1", "2", "3"]]


def test_sheet_reader_unknown_gid_raises() -> None:
    """Error: resolve_title failure propagates (Sheets fail path)."""

    def resolve_title(*, spreadsheet_id: str, sheet_id: int) -> str:
        raise ValueError(
            f"Sheet with id {sheet_id} was not found in spreadsheet {spreadsheet_id!r}",
        )

    def fetch_values(*, sheet_title: str, range_a1: str) -> list[list[Any]]:
        raise AssertionError("fetch_values must not be called when resolve fails")

    source = GoogleSheetsEventSource(
        credentials_file="creds.json",
        spreadsheet_id="ss-id",
        sheet_id=999,
        resolve_title=resolve_title,
        fetch_values=fetch_values,
    )

    with pytest.raises(ValueError, match="Sheet with id 999"):
        source.read_event_rows()
