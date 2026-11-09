from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.infrastructure.machine_pnl.sheets_unit_cost_catalog import (
    build_unit_cost_catalog_from_rows,
    load_unit_cost_sheet_rows,
)

_CANONICAL_HEADER = ["product_code", "unit_cost", "valid_from", "valid_to"]


def test_build_unit_cost_catalog_from_rows_get_uses_effective_unit_cost() -> None:
    catalog = build_unit_cost_catalog_from_rows(
        [
            _CANONICAL_HEADER,
            ["SKU-1", "10.00", "2026-01-01", "2026-03-31"],
            ["SKU-1", "12.00", "2026-04-01", ""],
        ]
    )
    assert catalog.get("SKU-1", as_of=date(2026, 2, 15)) == Decimal("10.00")
    assert catalog.get("SKU-1", as_of=date(2026, 4, 10)) == Decimal("12.00")
    assert catalog.get("SKU-MISSING", as_of=date(2026, 4, 10)) is None


def test_load_unit_cost_sheet_rows_wraps_read_sheet_rows(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_read(
        *,
        credentials_file: str,
        spreadsheet_id: str,
        sheet_id: int,
    ) -> list[list[str]]:
        calls.append(
            {
                "credentials_file": credentials_file,
                "spreadsheet_id": spreadsheet_id,
                "sheet_id": sheet_id,
            }
        )
        return [_CANONICAL_HEADER, ["SKU-1", "1.00", "2026-01-01", ""]]

    monkeypatch.setattr(
        "src.infrastructure.machine_pnl.sheets_unit_cost_catalog.read_sheet_rows",
        fake_read,
    )
    rows = load_unit_cost_sheet_rows(
        credentials_file="creds.json",
        spreadsheet_id="sheet-abc",
        sheet_id=7,
    )
    assert rows == [_CANONICAL_HEADER, ["SKU-1", "1.00", "2026-01-01", ""]]
    assert calls == [
        {
            "credentials_file": "creds.json",
            "spreadsheet_id": "sheet-abc",
            "sheet_id": 7,
        }
    ]
