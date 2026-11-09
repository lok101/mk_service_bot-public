from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from beartype import beartype

from src.application.sales_monitoring.ports import SalesSheetExportRow
from src.application.sales_monitoring.sales_sheet_export import (
    SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE,
)
from src.infrastructure.integrations.google.sheets.sheet_reader import (  # noqa: SLF001
    _get_rate_limiter,
    resolve_sheet_title,
)

SALES_SHEET_EXPORT_TRIM_CHUNK_SIZE = 5000
SALES_SHEET_EXPORT_API_MAX_ATTEMPTS = 3
SALES_SHEET_EXPORT_API_RETRY_DELAY_SECONDS = 1

__all__ = [
    "SALES_SHEET_EXPORT_API_MAX_ATTEMPTS",
    "SALES_SHEET_EXPORT_API_RETRY_DELAY_SECONDS",
    "SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE",
    "SALES_SHEET_EXPORT_TRIM_CHUNK_SIZE",
    "GoogleSheetsSalesSheetExportWriter",
]


@beartype
@dataclass(frozen=True, slots=True)
class GoogleSheetsSalesSheetExportWriter:
    service_factory: Callable[[], Any]
    spreadsheet_id: str
    sheet_id: int
    sleep: Callable[[float], None] = time.sleep
    count_data_rows: Callable[[], int] | None = None

    @beartype
    def ensure_header(self, headers: Sequence[str]) -> None:
        header_values = [list(headers)]

        def _op(service: Any) -> None:
            title = resolve_sheet_title(
                service=service,
                spreadsheet_id=self.spreadsheet_id,
                sheet_id=self.sheet_id,
            )
            result = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{title}'!A1",
                )
                .execute()
            )
            values = result.get("values") if isinstance(result, dict) else None
            if not isinstance(values, list) or not values:
                a1_empty = True
            else:
                first_row = values[0]
                a1_empty = (
                    not isinstance(first_row, list)
                    or not first_row
                    or not str(first_row[0]).strip()
                )
            if not a1_empty:
                return
            service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{title}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": header_values},
            ).execute()

        self._with_retry(_op)

    @beartype
    def append_rows(self, rows: Sequence[SalesSheetExportRow]) -> None:
        if not rows:
            return
        body_rows = [list(row.values) for row in rows]
        for offset in range(0, len(body_rows), SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE):
            chunk = body_rows[offset : offset + SALES_SHEET_EXPORT_APPEND_CHUNK_SIZE]

            def _op(service: Any, *, values: list[list[str]] = chunk) -> None:
                title = resolve_sheet_title(
                    service=service,
                    spreadsheet_id=self.spreadsheet_id,
                    sheet_id=self.sheet_id,
                )
                service.spreadsheets().values().append(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{title}'!A1",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": values},
                ).execute()

            self._with_retry(_op)

    @beartype
    def trim_to_max_data_rows(self, max_rows: int) -> int:
        if self.count_data_rows is not None:
            data_rows = self.count_data_rows()
        else:
            data_rows = self._count_data_rows_via_api()
        if data_rows <= max_rows:
            return 0
        to_remove = data_rows - max_rows
        removed = 0
        while removed < to_remove:
            chunk = min(to_remove - removed, SALES_SHEET_EXPORT_TRIM_CHUNK_SIZE)
            start_index = 1
            end_index = start_index + chunk

            def _op(
                service: Any,
                *,
                start: int = start_index,
                end: int = end_index,
            ) -> None:
                service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "requests": [
                            {
                                "deleteDimension": {
                                    "range": {
                                        "sheetId": self.sheet_id,
                                        "dimension": "ROWS",
                                        "startIndex": start,
                                        "endIndex": end,
                                    }
                                }
                            }
                        ]
                    },
                ).execute()

            self._with_retry(_op)
            removed += chunk
        return removed

    @beartype
    def _count_data_rows_via_api(self) -> int:
        counted: dict[str, int] = {"n": 0}

        def _op(service: Any) -> None:
            title = resolve_sheet_title(
                service=service,
                spreadsheet_id=self.spreadsheet_id,
                sheet_id=self.sheet_id,
            )
            result = (
                service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{title}'!A:A",
                )
                .execute()
            )
            values = result.get("values") if isinstance(result, dict) else None
            if not isinstance(values, list) or not values:
                counted["n"] = 0
                return
            counted["n"] = max(0, len(values) - 1)

        self._with_retry(_op)
        return counted["n"]

    @beartype
    def _with_retry(self, operation: Callable[[Any], None]) -> None:
        last_error: Exception | None = None
        for attempt in range(1, SALES_SHEET_EXPORT_API_MAX_ATTEMPTS + 1):
            _get_rate_limiter().acquire()
            service = self.service_factory()
            try:
                operation(service)
                return
            except Exception as exc:
                last_error = exc
                if attempt < SALES_SHEET_EXPORT_API_MAX_ATTEMPTS:
                    self.sleep(SALES_SHEET_EXPORT_API_RETRY_DELAY_SECONDS)
            finally:
                close = getattr(service, "close", None)
                if callable(close):
                    close()
        assert last_error is not None
        raise last_error
