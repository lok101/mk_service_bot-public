from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from beartype import beartype
from google.oauth2 import service_account
from googleapiclient.discovery import build

from src.infrastructure.integrations.google.sheets.sheet_reader import (
    GOOGLE_SHEETS_READONLY_SCOPE,
    resolve_sheet_title,
)

FetchValues = Callable[..., list[list[Any]]]
ResolveTitle = Callable[..., str]


@beartype
def _read_via_sheets_api(
    *,
    credentials_file: str,
    spreadsheet_id: str,
    sheet_id: int,
) -> list[list[Any]]:
    credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
        credentials_file,
        scopes=[GOOGLE_SHEETS_READONLY_SCOPE],
    )
    service = build("sheets", "v4", credentials=credentials)
    try:
        title = resolve_sheet_title(
            service=service,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
        )
        range_a1 = f"'{title}'!A:C"
        raw_values = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=range_a1,
                valueRenderOption="FORMATTED_VALUE",
            )
            .execute()
        )
    finally:
        service.close()
    values = raw_values.get("values", [])
    if not isinstance(values, list):
        raise ValueError("Sheet values must be a list")
    return [row for row in values if isinstance(row, list)]


@beartype
@dataclass(frozen=True, slots=True)
class GoogleSheetsEventSource:
    """Read event calendar sheet columns A–C as formatted strings (by gid)."""

    credentials_file: str
    spreadsheet_id: str
    sheet_id: int
    resolve_title: ResolveTitle | None = None
    fetch_values: FetchValues | None = None

    @beartype
    def read_event_rows(self) -> list[list[str]]:
        if self.resolve_title is not None or self.fetch_values is not None:
            if self.resolve_title is None or self.fetch_values is None:
                raise ValueError(
                    "resolve_title and fetch_values must both be set for injectable path",
                )
            title = self.resolve_title(
                spreadsheet_id=self.spreadsheet_id,
                sheet_id=self.sheet_id,
            )
            range_a1 = f"'{title}'!A:C"
            raw = self.fetch_values(sheet_title=title, range_a1=range_a1)
        else:
            raw = _read_via_sheets_api(
                credentials_file=self.credentials_file,
                spreadsheet_id=self.spreadsheet_id,
                sheet_id=self.sheet_id,
            )
        rows = [row for row in raw if isinstance(row, list)]
        return [[str(cell) for cell in row] for row in rows]
