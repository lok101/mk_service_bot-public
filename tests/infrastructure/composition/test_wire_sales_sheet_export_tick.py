from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.sales_monitoring.sales_sheet_export import SalesSheetExportResult
from src.infrastructure.composition.wiring.wire_sales_sheet_export import (
    run_sales_sheet_export_tick,
)


def test_export_tick_alerts_and_reraises_on_failure() -> None:
    alerts: list[str] = []

    def boom() -> SalesSheetExportResult:
        raise RuntimeError("sheets down")

    with pytest.raises(RuntimeError, match="sheets down"):
        run_sales_sheet_export_tick(execute=boom, notify_alert=alerts.append)

    assert alerts == ["sales_monitoring sales_sheet_export failed"]


def test_export_tick_returns_result_on_success() -> None:
    alerts: list[str] = []
    expected = SalesSheetExportResult(
        mode="incremental",
        exported_count=2,
        trimmed_count=0,
        pages=1,
        cursor_occurred_at=datetime(2026, 7, 30, tzinfo=UTC),
        cursor_source_id="s2",
    )

    def ok() -> SalesSheetExportResult:
        return expected

    result = run_sales_sheet_export_tick(execute=ok, notify_alert=alerts.append)
    assert result == expected
    assert alerts == []
