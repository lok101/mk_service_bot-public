from __future__ import annotations

import logging

from beartype import beartype
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.config.settings import get_settings
from src.infrastructure.rate_limiting import SyncGlobalBackoff, SyncRateLimiter

GOOGLE_SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
GOOGLE_SHEETS_WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

_LOGGER = logging.getLogger(__name__)

_TOO_MANY_REQUESTS_STATUS = 429

_title_cache: dict[tuple[str, int], str] = {}
_rate_limiter: SyncRateLimiter | None = None
_backoff: SyncGlobalBackoff | None = None


def _get_rate_limiter() -> SyncRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        settings = get_settings().google_sheets
        _rate_limiter = SyncRateLimiter(
            max_requests=settings.rate_limit_requests_per_window,
            time_window=settings.rate_limit_window_seconds,
        )
    return _rate_limiter


def _get_backoff() -> SyncGlobalBackoff:
    global _backoff
    if _backoff is None:
        settings = get_settings().google_sheets
        _backoff = SyncGlobalBackoff(timeout=settings.rate_limit_backoff_seconds)
    return _backoff


def _is_too_many_requests(exc: HttpError) -> bool:
    return bool(exc.status_code == _TOO_MANY_REQUESTS_STATUS)


def _resolve_sheet_title_cached(*, service: object, spreadsheet_id: str, sheet_id: int) -> str:
    key = (spreadsheet_id, sheet_id)
    cached = _title_cache.get(key)
    if cached is not None:
        return cached
    _get_backoff().wait_if_blocked()
    _get_rate_limiter().acquire()
    title = resolve_sheet_title(service=service, spreadsheet_id=spreadsheet_id, sheet_id=sheet_id)
    _title_cache[key] = title
    return title


def _read_sheet_rows_once(
    *,
    credentials_file: str,
    spreadsheet_id: str,
    sheet_id: int,
) -> list[list[str]]:
    credentials = service_account.Credentials.from_service_account_file(
        credentials_file,
        scopes=[GOOGLE_SHEETS_READONLY_SCOPE],
    )
    service = build("sheets", "v4", credentials=credentials)

    try:
        sheet_title = _resolve_sheet_title_cached(
            service=service,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
        )
        _get_backoff().wait_if_blocked()
        _get_rate_limiter().acquire()
        raw_values = (
            service.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"'{sheet_title}'",
            )
            .execute()
        )
    finally:
        service.close()

    values = raw_values.get("values", [])
    if not isinstance(values, list):
        raise ValueError("Sheet values must be a list")

    rows = [row for row in values if isinstance(row, list)]
    return [[str(cell) for cell in row] for row in rows]


@beartype
def read_sheet_rows(
    *,
    credentials_file: str,
    spreadsheet_id: str,
    sheet_id: int,
) -> list[list[str]]:
    try:
        return _read_sheet_rows_once(
            credentials_file=credentials_file,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
        )
    except HttpError as exc:
        if not _is_too_many_requests(exc):
            raise
        _LOGGER.warning(
            "google_sheets_rate_limit_backoff_triggered",
            extra={"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id},
        )
        _get_backoff().trigger_backoff()
        try:
            return _read_sheet_rows_once(
                credentials_file=credentials_file,
                spreadsheet_id=spreadsheet_id,
                sheet_id=sheet_id,
            )
        except HttpError as retry_exc:
            if _is_too_many_requests(retry_exc):
                _LOGGER.error(
                    "google_sheets_rate_limit_retry_failed",
                    extra={"spreadsheet_id": spreadsheet_id, "sheet_id": sheet_id},
                )
            raise


@beartype
def resolve_sheet_title(
    *,
    service: object,
    spreadsheet_id: str,
    sheet_id: int,
) -> str:
    raw_spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    if not isinstance(raw_spreadsheet, dict):
        raise ValueError("Spreadsheet metadata must be an object")

    raw_sheets = raw_spreadsheet.get("sheets", [])
    if not isinstance(raw_sheets, list):
        raise ValueError("Spreadsheet sheets must be a list")

    for raw_sheet in raw_sheets:
        if not isinstance(raw_sheet, dict):
            continue

        raw_properties = raw_sheet.get("properties")
        if not isinstance(raw_properties, dict):
            continue

        raw_sheet_id = raw_properties.get("sheetId")
        raw_title = raw_properties.get("title")
        if raw_sheet_id == sheet_id and isinstance(raw_title, str) and raw_title:
            return raw_title

    raise ValueError(
        f"Sheet with id {sheet_id} was not found in spreadsheet {spreadsheet_id!r}",
    )
