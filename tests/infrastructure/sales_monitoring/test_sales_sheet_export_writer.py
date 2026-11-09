from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.application.sales_monitoring.ports import SalesSheetExportRow
from src.application.sales_monitoring.sales_sheet_export import SALES_SHEET_EXPORT_HEADERS
from src.infrastructure.sales_monitoring.sales_sheet_export_writer import (
    SALES_SHEET_EXPORT_API_MAX_ATTEMPTS,
    SALES_SHEET_EXPORT_API_RETRY_DELAY_SECONDS,
    SALES_SHEET_EXPORT_TRIM_CHUNK_SIZE,
    GoogleSheetsSalesSheetExportWriter,
)


@pytest.fixture(autouse=True)
def _stub_sheets_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = MagicMock()
    monkeypatch.setattr(
        "src.infrastructure.sales_monitoring.sales_sheet_export_writer._get_rate_limiter",
        lambda: limiter,
    )


class _ValuesApi:
    def __init__(self, recorder: dict[str, Any], a1: str | None) -> None:
        self._recorder = recorder
        self._a1 = a1

    def get(self, **kwargs: object) -> Any:
        self._recorder.setdefault("gets", []).append(kwargs)

        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                if self._a1 is None:
                    return {"values": []}
                return {"values": [[self._a1]]}

        return _Exec()

    def append(self, **kwargs: object) -> Any:
        self._recorder.setdefault("appends", []).append(kwargs)

        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                return {}

        return _Exec()

    def update(self, **kwargs: object) -> Any:
        self._recorder.setdefault("updates", []).append(kwargs)

        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                return {}

        return _Exec()


class _Spreadsheets:
    def __init__(self, recorder: dict[str, Any], a1: str | None) -> None:
        self._recorder = recorder
        self._a1 = a1

    def values(self) -> _ValuesApi:
        return _ValuesApi(self._recorder, self._a1)

    def batchUpdate(self, **kwargs: object) -> Any:
        self._recorder.setdefault("batchUpdates", []).append(kwargs)

        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                return {}

        return _Exec()

    def get(self, **kwargs: object) -> Any:
        class _Exec:
            def execute(inner_self) -> dict[str, object]:
                return {
                    "sheets": [
                        {"properties": {"sheetId": 9, "title": "Sales"}},
                    ]
                }

        return _Exec()


class _Service:
    def __init__(self, recorder: dict[str, Any], a1: str | None) -> None:
        self._recorder = recorder
        self._a1 = a1

    def spreadsheets(self) -> _Spreadsheets:
        return _Spreadsheets(self._recorder, self._a1)

    def close(self) -> None:
        return None


def _writer(recorder: dict[str, Any], *, a1: str | None) -> GoogleSheetsSalesSheetExportWriter:
    return GoogleSheetsSalesSheetExportWriter(
        service_factory=lambda: _Service(recorder, a1),
        spreadsheet_id="ssid",
        sheet_id=9,
        sleep=lambda _s: None,
    )


def test_sales_sheet_export_writer_acquires_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = MagicMock()
    monkeypatch.setattr(
        "src.infrastructure.sales_monitoring.sales_sheet_export_writer._get_rate_limiter",
        lambda: limiter,
    )
    writer = GoogleSheetsSalesSheetExportWriter(
        service_factory=lambda: (_ for _ in ()).throw(AssertionError("no api")),
        spreadsheet_id="sid",
        sheet_id=1,
    )
    with pytest.raises(AssertionError):
        writer.ensure_header(["a"])
    limiter.acquire.assert_called()


def test_ensure_header_writes_when_a1_empty() -> None:
    rec: dict[str, Any] = {}
    w = _writer(rec, a1=None)
    w.ensure_header(SALES_SHEET_EXPORT_HEADERS)
    assert (
        any(
            a.get("body", {}).get("values") == [list(SALES_SHEET_EXPORT_HEADERS)]
            for a in rec.get("appends", [])
        )
        or any(
            u.get("body", {}).get("values") == [list(SALES_SHEET_EXPORT_HEADERS)]
            for u in rec.get("updates", [])
        )
        or any("updates" in str(b) for b in rec.get("batchUpdates", []))
    )


def test_ensure_header_noop_when_a1_set() -> None:
    rec: dict[str, Any] = {}
    w = _writer(rec, a1="Дата и время")
    w.ensure_header(SALES_SHEET_EXPORT_HEADERS)
    assert rec.get("appends", []) == []
    assert rec.get("updates", []) == []
    assert rec.get("batchUpdates", []) == []


def test_append_chunks_at_2000() -> None:
    rec: dict[str, Any] = {}
    w = _writer(rec, a1="x")
    rows = [SalesSheetExportRow(values=("a", "b", "c", "d", "e", "f", "g")) for _ in range(2001)]
    w.append_rows(rows)
    assert len(rec["appends"]) == 2
    assert len(rec["appends"][0]["body"]["values"]) == 2000
    assert len(rec["appends"][1]["body"]["values"]) == 1


def test_trim_preserves_header_and_chunks_deletes() -> None:
    rec: dict[str, Any] = {}
    w = GoogleSheetsSalesSheetExportWriter(
        service_factory=lambda: _Service(rec, "hdr"),
        spreadsheet_id="ssid",
        sheet_id=9,
        sleep=lambda _s: None,
        count_data_rows=lambda: 12_000,
    )
    removed = w.trim_to_max_data_rows(10_000)
    assert removed == 2_000
    assert rec["batchUpdates"]
    assert SALES_SHEET_EXPORT_TRIM_CHUNK_SIZE == 5000
    first = rec["batchUpdates"][0]
    requests = first["body"]["requests"]
    delete_range = requests[0]["deleteDimension"]["range"]
    assert delete_range["startIndex"] == 1
    assert delete_range["endIndex"] == 2001
    assert delete_range["dimension"] == "ROWS"
    assert delete_range["sheetId"] == 9


def test_trim_chunks_when_removal_exceeds_trim_chunk() -> None:
    rec: dict[str, Any] = {}
    w = GoogleSheetsSalesSheetExportWriter(
        service_factory=lambda: _Service(rec, "hdr"),
        spreadsheet_id="ssid",
        sheet_id=9,
        sleep=lambda _s: None,
        count_data_rows=lambda: 12_000,
    )
    removed = w.trim_to_max_data_rows(1_000)
    assert removed == 11_000
    assert len(rec["batchUpdates"]) == 3
    chunk_sizes: list[int] = []
    for batch in rec["batchUpdates"]:
        delete_range = batch["body"]["requests"][0]["deleteDimension"]["range"]
        assert delete_range["startIndex"] == 1
        chunk_sizes.append(delete_range["endIndex"] - delete_range["startIndex"])
    assert chunk_sizes == [5000, 5000, 1000]


def test_append_retries_three_times_then_raises() -> None:
    sleeps: list[float] = []
    attempts = {"n": 0}

    class _FailingValues:
        def append(self, **kwargs: object) -> Any:
            class _Exec:
                def execute(inner_self) -> dict[str, object]:
                    attempts["n"] += 1
                    raise RuntimeError("transient")

            return _Exec()

    class _FailingSpreadsheets:
        def values(self) -> _FailingValues:
            return _FailingValues()

        def get(self, **kwargs: object) -> Any:
            class _Exec:
                def execute(inner_self) -> dict[str, object]:
                    return {
                        "sheets": [
                            {"properties": {"sheetId": 9, "title": "Sales"}},
                        ]
                    }

            return _Exec()

    class _FailingService:
        def spreadsheets(self) -> _FailingSpreadsheets:
            return _FailingSpreadsheets()

        def close(self) -> None:
            return None

    writer = GoogleSheetsSalesSheetExportWriter(
        service_factory=lambda: _FailingService(),
        spreadsheet_id="ssid",
        sheet_id=9,
        sleep=sleeps.append,
    )
    row = SalesSheetExportRow(values=("a", "b", "c", "d", "e", "f", "g"))
    with pytest.raises(RuntimeError, match="transient"):
        writer.append_rows([row])
    assert attempts["n"] == SALES_SHEET_EXPORT_API_MAX_ATTEMPTS == 3
    assert sleeps == [SALES_SHEET_EXPORT_API_RETRY_DELAY_SECONDS] * 2
    assert SALES_SHEET_EXPORT_API_RETRY_DELAY_SECONDS == 1


def test_trim_counts_data_rows_via_api_when_hook_absent() -> None:
    rec: dict[str, Any] = {}
    column_a = [["hdr"], ["1"], ["2"], ["3"], ["4"], ["5"]]

    class _CountingValues:
        def get(self, **kwargs: object) -> Any:
            rec.setdefault("gets", []).append(kwargs)

            class _Exec:
                def execute(inner_self) -> dict[str, object]:
                    range_name = str(kwargs.get("range", ""))
                    if range_name.endswith("!A1"):
                        return {"values": [["hdr"]]}
                    return {"values": column_a}

            return _Exec()

        def append(self, **kwargs: object) -> Any:
            raise AssertionError("append should not be called")

        def update(self, **kwargs: object) -> Any:
            raise AssertionError("update should not be called")

    class _CountingSpreadsheets:
        def values(self) -> _CountingValues:
            return _CountingValues()

        def batchUpdate(self, **kwargs: object) -> Any:
            rec.setdefault("batchUpdates", []).append(kwargs)

            class _Exec:
                def execute(inner_self) -> dict[str, object]:
                    return {}

            return _Exec()

        def get(self, **kwargs: object) -> Any:
            class _Exec:
                def execute(inner_self) -> dict[str, object]:
                    return {
                        "sheets": [
                            {"properties": {"sheetId": 9, "title": "Sales"}},
                        ]
                    }

            return _Exec()

    class _CountingService:
        def spreadsheets(self) -> _CountingSpreadsheets:
            return _CountingSpreadsheets()

        def close(self) -> None:
            return None

    writer = GoogleSheetsSalesSheetExportWriter(
        service_factory=lambda: _CountingService(),
        spreadsheet_id="ssid",
        sheet_id=9,
        sleep=lambda _s: None,
    )
    removed = writer.trim_to_max_data_rows(3)
    assert removed == 2
    assert any(str(g.get("range", "")).endswith("!A:A") for g in rec["gets"])
    delete_range = rec["batchUpdates"][0]["body"]["requests"][0]["deleteDimension"]["range"]
    assert delete_range["startIndex"] == 1
    assert delete_range["endIndex"] == 3
