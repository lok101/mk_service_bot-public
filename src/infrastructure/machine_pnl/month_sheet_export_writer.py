from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from beartype import beartype

from src.application.machine_pnl import MonthPnlSnapshot
from src.application.shared.sheet_cell_format import (
    format_sheet_date,
    format_sheet_datetime,
    format_sheet_decimal,
    parse_sheet_date,
)
from src.infrastructure.integrations.google.sheets.sheet_reader import (  # noqa: SLF001
    _get_rate_limiter,
    resolve_sheet_title,
)

_LOGGER = logging.getLogger(__name__)

MONTH_PNL_SHEET_API_MAX_ATTEMPTS = 3
MONTH_PNL_SHEET_API_RETRY_DELAY_SECONDS = 1

MONTH_PNL_SHEET_HEADERS: tuple[str, ...] = (
    "machine_id",
    "location_name",
    "technician_name",
    "company_name",
    "location_id",
    "company_id",
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

_STALE_COLUMN_PAD: tuple[str, str] = ("", "")

_OPEX_SHEET_KEYS: tuple[str, ...] = (
    "rent_fixed",
    "rent_percent",
    "terminal",
    "labor",
    "acquiring_percent",
    "acquiring_per_sale",
)

__all__ = [
    "MONTH_PNL_SHEET_API_MAX_ATTEMPTS",
    "MONTH_PNL_SHEET_API_RETRY_DELAY_SECONDS",
    "MONTH_PNL_SHEET_HEADERS",
    "MonthPnlSheetExportWriter",
]


@beartype
def _a1_empty(values: list[list[str]] | None) -> bool:
    if not values:
        return True
    first_row = values[0]
    if not isinstance(first_row, list) or not first_row:
        return True
    return not str(first_row[0]).strip()


@beartype
def _optional_text(value: str | None) -> str:
    return value if value is not None else ""


@beartype
def _format_opex_amount(breakdown: dict[str, Decimal | None], key: str) -> str:
    amount = breakdown.get(key)
    if amount is None:
        return ""
    return format_sheet_decimal(amount)


@beartype
def _snapshot_to_row(
    snapshot: MonthPnlSnapshot,
    tz: ZoneInfo,
    *,
    location_display_lookup: Callable[[str], str] | None = None,
    technician_name_lookup: Callable[[str], str] | None = None,
    company_name_lookup: Callable[[int], str] | None = None,
) -> list[str]:
    breakdown = dict(snapshot.opex_breakdown)
    location_id = _optional_text(snapshot.location_id)
    location_name = ""
    if location_display_lookup is not None and location_id:
        location_name = location_display_lookup(location_id)
    technician_id = _optional_text(snapshot.technician_id)
    technician_name = ""
    if technician_name_lookup is not None and technician_id:
        technician_name = technician_name_lookup(technician_id)
    company_id_text = "" if snapshot.company_id is None else str(snapshot.company_id)
    company_name = ""
    if company_name_lookup is not None and snapshot.company_id is not None:
        company_name = company_name_lookup(snapshot.company_id)
    return [
        snapshot.machine_id.value,
        location_name,
        technician_name,
        company_name,
        location_id,
        company_id_text,
        technician_id,
        format_sheet_date(snapshot.period_start),
        format_sheet_date(snapshot.period_end),
        format_sheet_decimal(snapshot.revenue),
        format_sheet_date(snapshot.revenue_known_as_of),
        format_sheet_decimal(snapshot.cogs_expected),
        format_sheet_decimal(snapshot.cogs_actual_fact),
        format_sheet_decimal(snapshot.cogs_actual_estimate),
        format_sheet_decimal(snapshot.allocated_shortage_fact),
        format_sheet_decimal(snapshot.allocated_shortage_estimate),
        format_sheet_decimal(snapshot.allocated_surplus_fact),
        format_sheet_decimal(snapshot.allocated_surplus_estimate),
        *(_format_opex_amount(breakdown, key) for key in _OPEX_SHEET_KEYS),
        format_sheet_decimal(snapshot.opex_known_total),
        format_sheet_decimal(snapshot.net_theory),
        format_sheet_decimal(snapshot.machine_gap),
        format_sheet_decimal(snapshot.net_machine),
        format_sheet_decimal(snapshot.tech_gap),
        format_sheet_decimal(snapshot.net_after_tech),
        str(snapshot.coverage_days),
        str(snapshot.days_in_month),
        format_sheet_decimal(snapshot.coverage_pct),
        snapshot.projection_basis,
        ";".join(warning.code for warning in snapshot.warnings),
        format_sheet_datetime(snapshot.last_recomputed_at, tz),
        *_STALE_COLUMN_PAD,
    ]


@beartype
def _header_index(headers: Sequence[str], name: str) -> int:
    try:
        return list(headers).index(name)
    except ValueError:
        return MONTH_PNL_SHEET_HEADERS.index(name)


@beartype
def _existing_row_map(values: list[list[str]]) -> dict[tuple[str, date], int]:
    if not values:
        return {}
    headers = [str(cell) for cell in values[0]]
    machine_col = _header_index(headers, "machine_id")
    period_col = _header_index(headers, "period_start")
    mapping: dict[tuple[str, date], int] = {}
    for row_index, row in enumerate(values[1:], start=2):
        if len(row) <= max(machine_col, period_col):
            continue
        machine_id = str(row[machine_col]).strip()
        raw_period = str(row[period_col]).strip()
        if not machine_id or not raw_period:
            continue
        try:
            period_start = parse_sheet_date(raw_period)
        except ValueError:
            continue
        mapping[(machine_id, period_start)] = row_index
    return mapping


@beartype
@dataclass(frozen=True, slots=True)
class MonthPnlSheetExportWriter:
    service_factory: Callable[[], Any]
    spreadsheet_id: str
    sheet_id: int
    tz: ZoneInfo
    sleep: Callable[[float], None] = time.sleep
    location_display_lookup: Callable[[str], str] | None = None
    technician_name_lookup: Callable[[str], str] | None = None
    company_name_lookup: Callable[[int], str] | None = None

    @beartype
    def ensure_header(self, headers: Sequence[str]) -> None:
        header_values = [list(headers) + list(_STALE_COLUMN_PAD)]

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
            raw_values = result.get("values") if isinstance(result, dict) else None
            values: list[list[str]] | None = None
            if isinstance(raw_values, list):
                values = [
                    [str(cell) for cell in row] for row in raw_values if isinstance(row, list)
                ]
            if not _a1_empty(values):
                return
            service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{title}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": header_values},
            ).execute()

        self._with_retry(_op)

    @beartype
    def upsert_rows(self, snapshots: Sequence[MonthPnlSnapshot]) -> None:
        if not snapshots:
            return

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
                    range=f"'{title}'",
                )
                .execute()
            )
            raw_values = result.get("values") if isinstance(result, dict) else None
            values: list[list[str]] = []
            if isinstance(raw_values, list):
                values = [
                    [str(cell) for cell in row] for row in raw_values if isinstance(row, list)
                ]
            if _a1_empty(values):
                service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{title}'!A1",
                    valueInputOption="USER_ENTERED",
                    body={
                        "values": [list(MONTH_PNL_SHEET_HEADERS) + list(_STALE_COLUMN_PAD)],
                    },
                ).execute()
                if not values:
                    values = [list(MONTH_PNL_SHEET_HEADERS) + list(_STALE_COLUMN_PAD)]
            key_to_row = _existing_row_map(values)
            next_row = len(values) + 1 if values else 2
            updates: list[dict[str, Any]] = []
            new_rows: list[list[str]] = []
            for snapshot in snapshots:
                row = _snapshot_to_row(
                    snapshot,
                    self.tz,
                    location_display_lookup=self.location_display_lookup,
                    technician_name_lookup=self.technician_name_lookup,
                    company_name_lookup=self.company_name_lookup,
                )
                key = (snapshot.machine_id.value, snapshot.period_start)
                existing = key_to_row.get(key)
                if existing is not None:
                    updates.append(
                        {
                            "range": f"'{title}'!A{existing}",
                            "values": [row],
                        }
                    )
                    continue
                new_rows.append(row)
            if updates:
                service.spreadsheets().values().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "valueInputOption": "USER_ENTERED",
                        "data": updates,
                    },
                ).execute()
            # values.get omits trailing empty formatted rows; values.append uses
            # the sheet used-range and can write far below the visible table.
            if new_rows:
                service.spreadsheets().values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{title}'!A{next_row}",
                    valueInputOption="USER_ENTERED",
                    body={"values": new_rows},
                ).execute()
            _LOGGER.info(
                "machine_pnl_month_sheet_upsert updates=%s new_rows=%s snapshots=%s next_row=%s",
                len(updates),
                len(new_rows),
                len(snapshots),
                next_row,
            )

        self._with_retry(_op)

    @beartype
    def _with_retry(self, operation: Callable[[Any], None]) -> None:
        last_error: Exception | None = None
        for attempt in range(1, MONTH_PNL_SHEET_API_MAX_ATTEMPTS + 1):
            _get_rate_limiter().acquire()
            service = self.service_factory()
            try:
                operation(service)
                return
            except Exception as exc:
                last_error = exc
                if attempt < MONTH_PNL_SHEET_API_MAX_ATTEMPTS:
                    self.sleep(MONTH_PNL_SHEET_API_RETRY_DELAY_SECONDS)
            finally:
                close = getattr(service, "close", None)
                if callable(close):
                    close()
        assert last_error is not None
        raise last_error
