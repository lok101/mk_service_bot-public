from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from decimal import Decimal

from src.application.micromarket_loading.need_sheet import (
    NeedSourceLine,
    NeedSourceMachine,
    build_need_rows,
    need_rows_xlsx,
)


def test_export_xlsx_sums_need_and_omits_zero_rows() -> None:
    machines = (
        NeedSourceMachine(
            lines=(
                NeedSourceLine(
                    product_code="2311",
                    target_qty=5,
                    shelf_qty=Decimal("3"),
                    name="Салат",
                ),
                NeedSourceLine(
                    product_code="2312",
                    target_qty=1,
                    shelf_qty=Decimal("1"),
                    name="Вода",
                ),
            ),
        ),
        NeedSourceMachine(
            lines=(
                NeedSourceLine(
                    product_code="2311",
                    target_qty=10,
                    shelf_qty=Decimal("7"),
                    name="Салат",
                ),
            ),
        ),
    )
    rows = build_need_rows(machines)
    assert len(rows) == 1
    assert rows[0].product_code == "2311"
    assert rows[0].name == "Салат"
    assert rows[0].need_qty == Decimal("5")

    payload = need_rows_xlsx(rows)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
        shared = ""
        if "xl/sharedStrings.xml" in zf.namelist():
            shared = zf.read("xl/sharedStrings.xml").decode()
        blob = sheet + shared
        assert "2311" in blob
        assert "Салат" in blob
        assert "5" in blob
        assert "код" in blob
        assert "имя" in blob
        assert "нужно" in blob
        assert "поставщик" in blob
        assert "цена последнего закупа" in blob
        assert "количество в упаковке" in blob
        assert "название у поставщика" in blob
        assert "2312" not in blob


def test_export_xlsx_includes_arrival_meta_row() -> None:
    rows = build_need_rows(
        (
            NeedSourceMachine(
                lines=(
                    NeedSourceLine(
                        product_code="2311",
                        target_qty=5,
                        shelf_qty=Decimal("2"),
                        name="Салат",
                    ),
                ),
            ),
        ),
    )
    arrival = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    payload = need_rows_xlsx(rows, expected_arrival_at=arrival)
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        sheet = zf.read("xl/worksheets/sheet1.xml").decode()
        shared = ""
        if "xl/sharedStrings.xml" in zf.namelist():
            shared = zf.read("xl/sharedStrings.xml").decode()
        blob = sheet + shared
        assert "прибытие" in blob
        assert arrival.isoformat() in blob


def test_export_uses_draft_need_only_for_saved_product_codes() -> None:
    machines = (
        NeedSourceMachine(
            lines=(
                NeedSourceLine(
                    product_code="2311",
                    target_qty=10,
                    shelf_qty=Decimal("2"),
                    name="Салат",
                    draft_need_qty=Decimal("1"),
                ),
                NeedSourceLine(
                    product_code="2312",
                    target_qty=5,
                    shelf_qty=Decimal("1"),
                    name="Вода",
                    draft_need_qty=None,
                ),
            ),
        ),
    )
    rows = build_need_rows(machines)
    by_code = {row.product_code: row for row in rows}
    assert by_code["2311"].need_qty == Decimal("1")
    assert by_code["2312"].need_qty == Decimal("4")
