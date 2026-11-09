from __future__ import annotations

import pytest

from src.application.reference_data.models import ReferenceDataSourceId
from src.infrastructure.reference_data.sheets_source_reader import (
    SheetsReferenceDataSourceReader,
)

_SID = ReferenceDataSourceId.BOT_USERS


def test_read_rows_delegates_to_read_fn() -> None:
    calls: list[dict[str, object]] = []

    def fake_read(*, credentials_file: str, spreadsheet_id: str, sheet_id: int) -> list[list[str]]:
        calls.append(
            {
                "credentials_file": credentials_file,
                "spreadsheet_id": spreadsheet_id,
                "sheet_id": sheet_id,
            }
        )
        return [["id"], ["1"]]

    reader = SheetsReferenceDataSourceReader(
        credentials_file="creds.json",
        sources={_SID: ("sheet-abc", 42)},
        read_rows_fn=fake_read,
    )
    assert reader.read_rows(_SID) == [["id"], ["1"]]
    assert calls == [
        {"credentials_file": "creds.json", "spreadsheet_id": "sheet-abc", "sheet_id": 42},
    ]


def test_read_rows_unknown_source_raises() -> None:
    reader = SheetsReferenceDataSourceReader(
        credentials_file="creds.json",
        sources={},
    )
    with pytest.raises(KeyError):
        reader.read_rows(_SID)
