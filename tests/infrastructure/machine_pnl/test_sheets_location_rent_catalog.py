from __future__ import annotations

from decimal import Decimal

from src.application.machine_pnl.location_rent_sheet import RowsLocationRentCatalog
from src.domain.ids import MachineId
from src.infrastructure.machine_pnl.sheets_location_rent_catalog import (
    build_location_rent_catalog_from_rows,
    load_location_rent_sheet_rows,
)


def test_load_location_rent_sheet_rows_wraps_read_sheet_rows(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_read(**kwargs: object) -> list[list[str]]:
        captured.update(kwargs)
        return [
            [
                "Сумма",
                "Процент",
                "Id локации",
                "Id ТТ",
                "Имя",
                "Дата установки",
                "Дата снятия",
            ]
        ]

    monkeypatch.setattr(
        "src.infrastructure.machine_pnl.sheets_location_rent_catalog.read_sheet_rows",
        fake_read,
    )
    rows = load_location_rent_sheet_rows(
        credentials_file="creds.json",
        spreadsheet_id="ss",
        sheet_id=20,
    )
    assert captured["spreadsheet_id"] == "ss"
    assert captured["sheet_id"] == 20
    assert rows[0][0] == "Сумма"


def test_build_location_rent_catalog_from_rows() -> None:
    # happy
    header = [
        "Сумма",
        "Процент",
        "Id локации",
        "Id ТТ",
        "Имя",
        "Дата установки",
        "Дата снятия",
    ]
    catalog = build_location_rent_catalog_from_rows(
        [header, ["100", "", "loc-1", "101", "n", "01.05.2026", ""]]
    )
    assert isinstance(catalog, RowsLocationRentCatalog)
    occ = catalog.list_for_machine(MachineId("101"))
    assert len(occ) == 1
    assert occ[0].rent_monthly == Decimal("100")
