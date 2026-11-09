from __future__ import annotations

import zipfile
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from beartype import beartype

from src.domain.micromarket_loading.quantities import need_qty as calc_need_qty


@beartype
@dataclass(frozen=True, slots=True)
class NeedSourceLine:
    product_code: str
    target_qty: int
    shelf_qty: Decimal
    name: str = ""
    draft_need_qty: Decimal | None = None


@beartype
@dataclass(frozen=True, slots=True)
class NeedSourceMachine:
    lines: tuple[NeedSourceLine, ...]


@beartype
@dataclass(frozen=True, slots=True)
class NeedRow:
    product_code: str
    name: str
    need_qty: Decimal
    supplier_name: str | None = None
    last_buy_price: Decimal | None = None
    package_quantity: Decimal | None = None
    supplier_product_name: str | None = None


@beartype
def build_need_rows(machines: tuple[NeedSourceMachine, ...]) -> tuple[NeedRow, ...]:
    totals: dict[str, Decimal] = {}
    names: dict[str, str] = {}
    for machine in machines:
        for line in machine.lines:
            qty = (
                line.draft_need_qty
                if line.draft_need_qty is not None
                else calc_need_qty(target_qty=line.target_qty, shelf_qty=line.shelf_qty)
            )
            totals[line.product_code] = totals.get(line.product_code, Decimal("0")) + qty
            if line.name and (line.product_code not in names or not names.get(line.product_code)):
                names[line.product_code] = line.name
    rows: list[NeedRow] = []
    for code in sorted(totals):
        qty = totals[code]
        if qty == 0:
            continue
        rows.append(
            NeedRow(
                product_code=code,
                name=names.get(code, ""),
                need_qty=qty,
            ),
        )
    return tuple(rows)


@beartype
def need_rows_xlsx(
    rows: tuple[NeedRow, ...],
    *,
    expected_arrival_at: datetime | None = None,
) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" '
                'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                "</Types>"
            ),
        )
        zf.writestr(
            "_rels/.rels",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'officeDocument" '
                'Target="xl/workbook.xml"/>'
                "</Relationships>"
            ),
        )
        zf.writestr(
            "xl/workbook.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                "<sheets>"
                '<sheet name="need" sheetId="1" r:id="rId1"/>'
                "</sheets>"
                "</workbook>"
            ),
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'worksheet" '
                'Target="worksheets/sheet1.xml"/>'
                "</Relationships>"
            ),
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            _sheet_xml(rows, expected_arrival_at=expected_arrival_at),
        )
    return buffer.getvalue()


def _sheet_xml(
    rows: tuple[NeedRow, ...],
    *,
    expected_arrival_at: datetime | None,
) -> str:
    cells: list[str] = []
    row_index = 1
    if expected_arrival_at is not None:
        cells.append(
            _row_xml(
                row_index,
                (
                    "прибытие",
                    expected_arrival_at.isoformat(),
                    "",
                    "",
                    "",
                    "",
                    "",
                ),
            ),
        )
        row_index += 1
    headers = (
        "код",
        "имя",
        "нужно",
        "поставщик",
        "цена последнего закупа",
        "количество в упаковке",
        "название у поставщика",
    )
    cells.append(_row_xml(row_index, headers))
    row_index += 1
    for row in rows:
        cells.append(
            _row_xml(
                row_index,
                (
                    row.product_code,
                    row.name,
                    _decimal_cell(row.need_qty),
                    row.supplier_name or "",
                    _optional_decimal_cell(row.last_buy_price),
                    _optional_decimal_cell(row.package_quantity),
                    row.supplier_product_name or "",
                ),
            ),
        )
        row_index += 1
    body = "".join(cells)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{body}</sheetData>"
        "</worksheet>"
    )


def _decimal_cell(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _optional_decimal_cell(value: Decimal | None) -> str:
    if value is None:
        return ""
    return _decimal_cell(value)


def _row_xml(row_index: int, values: tuple[str, ...]) -> str:
    cols = ("A", "B", "C", "D", "E", "F", "G")
    parts: list[str] = []
    for col, value in zip(cols, values, strict=True):
        ref = f"{col}{row_index}"
        parts.append(
            f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>',
        )
    return f'<row r="{row_index}">{"".join(parts)}</row>'
