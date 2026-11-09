from __future__ import annotations

import time
from typing import Any

import pytest
from google.oauth2 import service_account
from googleapiclient.errors import HttpError

from src.infrastructure.integrations.google.sheets import sheet_reader
from src.infrastructure.rate_limiting import SyncGlobalBackoff, SyncRateLimiter


class _FakeResp:
    def __init__(self, status: int) -> None:
        self.status = status
        self.reason = "error"


def _http_error(status: int) -> HttpError:
    return HttpError(_FakeResp(status), b"{}")


class _RecordingBackoff(SyncGlobalBackoff):
    def __init__(self, timeout: float) -> None:
        super().__init__(timeout=timeout)
        self.trigger_calls = 0

    def trigger_backoff(self) -> None:
        self.trigger_calls += 1
        super().trigger_backoff()


class _FakeExecutable:
    def __init__(self, execute_fn: Any) -> None:
        self._execute_fn = execute_fn

    def execute(self) -> dict[str, Any]:
        return self._execute_fn()


class _FakeValuesResource:
    def __init__(self, service: _FakeSheetsService) -> None:
        self._service = service

    def get(self, *, spreadsheetId: str, range: str) -> _FakeExecutable:
        def execute() -> dict[str, Any]:
            self._service.values_calls += 1
            if self._service.values_errors:
                raise self._service.values_errors.pop(0)
            return {"values": self._service.rows}

        return _FakeExecutable(execute)


class _FakeSpreadsheetsResource:
    def __init__(self, service: _FakeSheetsService) -> None:
        self._service = service

    def get(self, *, spreadsheetId: str) -> _FakeExecutable:
        def execute() -> dict[str, Any]:
            self._service.metadata_calls += 1
            return {
                "sheets": [
                    {
                        "properties": {
                            "sheetId": self._service.sheet_id,
                            "title": self._service.sheet_title,
                        },
                    },
                ],
            }

        return _FakeExecutable(execute)

    def values(self) -> _FakeValuesResource:
        return _FakeValuesResource(self._service)


class _FakeSheetsService:
    def __init__(
        self,
        *,
        sheet_id: int = 1,
        sheet_title: str = "Sheet1",
        rows: list[list[str]] | None = None,
        values_errors: list[Exception] | None = None,
    ) -> None:
        self.sheet_id = sheet_id
        self.sheet_title = sheet_title
        self.rows = rows if rows is not None else [["a", "b"]]
        self.values_errors = list(values_errors or [])
        self.metadata_calls = 0
        self.values_calls = 0
        self.closed = False

    def spreadsheets(self) -> _FakeSpreadsheetsResource:
        return _FakeSpreadsheetsResource(self)

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_sheet_reader_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sheet_reader, "_title_cache", {})
    monkeypatch.setattr(sheet_reader, "_rate_limiter", None)
    monkeypatch.setattr(sheet_reader, "_backoff", None)
    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_file",
        lambda *args, **kwargs: object(),
    )


def _use_fake_service(monkeypatch: pytest.MonkeyPatch, service: _FakeSheetsService) -> None:
    monkeypatch.setattr(sheet_reader, "build", lambda *args, **kwargs: service)


def test_read_sheet_rows_skips_metadata_call_when_title_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # happy: второй read_sheet_rows с теми же id не делает повторный metadata-get
    service = _FakeSheetsService(rows=[["1", "2"]])
    _use_fake_service(monkeypatch, service)
    monkeypatch.setattr(
        sheet_reader, "_rate_limiter", SyncRateLimiter(max_requests=100, time_window=1.0)
    )
    monkeypatch.setattr(sheet_reader, "_backoff", SyncGlobalBackoff(timeout=0.01))

    first = sheet_reader.read_sheet_rows(
        credentials_file="creds.json", spreadsheet_id="ss-1", sheet_id=1
    )
    second = sheet_reader.read_sheet_rows(
        credentials_file="creds.json", spreadsheet_id="ss-1", sheet_id=1
    )

    assert first == [["1", "2"]]
    assert second == [["1", "2"]]
    assert service.metadata_calls == 1
    assert service.values_calls == 2


def test_read_sheet_rows_rate_limiter_blocks_second_call_within_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # edge: rate limiter не превышает max_requests за window (общий на metadata+values)
    service = _FakeSheetsService()
    _use_fake_service(monkeypatch, service)
    monkeypatch.setattr(
        sheet_reader, "_rate_limiter", SyncRateLimiter(max_requests=1, time_window=0.05)
    )
    monkeypatch.setattr(sheet_reader, "_backoff", SyncGlobalBackoff(timeout=0.01))
    sheet_reader._title_cache[("ss-1", 1)] = "Sheet1"

    sheet_reader.read_sheet_rows(credentials_file="creds.json", spreadsheet_id="ss-1", sheet_id=1)
    start = time.monotonic()
    sheet_reader.read_sheet_rows(credentials_file="creds.json", spreadsheet_id="ss-1", sheet_id=1)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.04


def test_read_sheet_rows_retries_once_after_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # error -> happy retry: HttpError 429 -> trigger_backoff + один повтор -> успех
    service = _FakeSheetsService(rows=[["ok"]], values_errors=[_http_error(429)])
    _use_fake_service(monkeypatch, service)
    monkeypatch.setattr(
        sheet_reader, "_rate_limiter", SyncRateLimiter(max_requests=100, time_window=1.0)
    )
    backoff = _RecordingBackoff(timeout=0.01)
    monkeypatch.setattr(sheet_reader, "_backoff", backoff)

    rows = sheet_reader.read_sheet_rows(
        credentials_file="creds.json", spreadsheet_id="ss-1", sheet_id=1
    )

    assert rows == [["ok"]]
    assert backoff.trigger_calls == 1
    assert service.values_calls == 2


def test_read_sheet_rows_raises_after_second_consecutive_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # error: второй 429 подряд -> исключение наружу
    service = _FakeSheetsService(values_errors=[_http_error(429), _http_error(429)])
    _use_fake_service(monkeypatch, service)
    monkeypatch.setattr(
        sheet_reader, "_rate_limiter", SyncRateLimiter(max_requests=100, time_window=1.0)
    )
    backoff = _RecordingBackoff(timeout=0.01)
    monkeypatch.setattr(sheet_reader, "_backoff", backoff)

    with pytest.raises(HttpError):
        sheet_reader.read_sheet_rows(
            credentials_file="creds.json", spreadsheet_id="ss-1", sheet_id=1
        )

    assert backoff.trigger_calls == 1
    assert service.values_calls == 2
