from __future__ import annotations

import csv
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import xlrd
from beartype import beartype
from openpyxl import load_workbook

from src.application.product_identity import (
    FILE_EMPTY_TEXT,
    FILE_UNREADABLE_TEXT,
    DomainProductImportRow,
)

_SUPPORTED_SUFFIXES = frozenset({".csv", ".xls", ".xlsx"})


class DomainProductImportParseError(Exception):
    @beartype
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@beartype
def parse_domain_product_import_file(
    data: bytes,
    *,
    filename: str,
) -> tuple[DomainProductImportRow, ...]:
    suffix = Path(filename).suffix.casefold()
    if suffix not in _SUPPORTED_SUFFIXES:
        raise DomainProductImportParseError(FILE_UNREADABLE_TEXT)
    if suffix == ".csv":
        return _parse_csv(data)
    if suffix == ".xlsx":
        return _parse_xlsx(data)
    return _parse_xls(data)


@beartype
def _parse_csv(data: bytes) -> tuple[DomainProductImportRow, ...]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1251")
        except UnicodeDecodeError as exc:
            raise DomainProductImportParseError(FILE_UNREADABLE_TEXT) from exc

    first_line = text.splitlines()[0] if text else ""
    delimiter = _detect_delimiter(first_line)
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    rows: list[DomainProductImportRow] = []
    for index, columns in enumerate(reader):
        if index == 0:
            continue
        name = columns[0].strip() if columns else ""
        catalog_code = columns[1].strip() if len(columns) > 1 else ""
        if not name and not catalog_code:
            continue
        rows.append(
            DomainProductImportRow(
                line_number=index + 1,
                name=name,
                catalog_code=catalog_code,
            )
        )
    if not rows:
        raise DomainProductImportParseError(FILE_EMPTY_TEXT)
    return tuple(rows)


@beartype
def _detect_delimiter(first_line: str) -> str:
    commas = 0
    semicolons = 0
    in_quotes = False
    for char in first_line:
        if char == '"':
            in_quotes = not in_quotes
            continue
        if in_quotes:
            continue
        if char == ",":
            commas += 1
        elif char == ";":
            semicolons += 1
    if semicolons > commas:
        return ";"
    return ","


@beartype
def _cell_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(Decimal(str(value)), "f")
    return str(value).strip()


@beartype
def _rows_from_matrix(
    matrix: list[list[object]],
) -> tuple[DomainProductImportRow, ...]:
    rows: list[DomainProductImportRow] = []
    for index, columns in enumerate(matrix):
        if index == 0:
            continue
        name = _cell_str(columns[0]) if columns else ""
        catalog_code = _cell_str(columns[1]) if len(columns) > 1 else ""
        if not name and not catalog_code:
            continue
        rows.append(
            DomainProductImportRow(
                line_number=index + 1,
                name=name,
                catalog_code=catalog_code,
            )
        )
    if not rows:
        raise DomainProductImportParseError(FILE_EMPTY_TEXT)
    return tuple(rows)


@beartype
def _parse_xlsx(data: bytes) -> tuple[DomainProductImportRow, ...]:
    try:
        workbook = load_workbook(BytesIO(data), data_only=True, read_only=True)
    except Exception as exc:
        raise DomainProductImportParseError(FILE_UNREADABLE_TEXT) from exc
    try:
        sheets = workbook.worksheets
        if not sheets:
            raise DomainProductImportParseError(FILE_UNREADABLE_TEXT)
        sheet = sheets[0]
        matrix: list[list[object]] = []
        for row in sheet.iter_rows(values_only=True):
            matrix.append(list(row))
    except DomainProductImportParseError:
        raise
    except Exception as exc:
        raise DomainProductImportParseError(FILE_UNREADABLE_TEXT) from exc
    finally:
        workbook.close()
    return _rows_from_matrix(matrix)


@beartype
def _parse_xls(data: bytes) -> tuple[DomainProductImportRow, ...]:
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as exc:
        raise DomainProductImportParseError(FILE_UNREADABLE_TEXT) from exc
    try:
        if book.nsheets < 1:
            raise DomainProductImportParseError(FILE_UNREADABLE_TEXT)
        sheet = book.sheet_by_index(0)
        matrix: list[list[object]] = []
        for row_index in range(sheet.nrows):
            row_values: list[object] = []
            for col_index in range(sheet.ncols):
                row_values.append(_xls_cell_value(sheet, row_index, col_index))
            matrix.append(row_values)
    except DomainProductImportParseError:
        raise
    except Exception as exc:
        raise DomainProductImportParseError(FILE_UNREADABLE_TEXT) from exc
    return _rows_from_matrix(matrix)


@beartype
def _xls_cell_value(sheet: Any, row_index: int, col_index: int) -> object:
    cell = sheet.cell(row_index, col_index)
    if cell.ctype == xlrd.XL_CELL_EMPTY:
        return None
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        return float(cell.value)
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    if cell.ctype == xlrd.XL_CELL_DATE:
        return cell.value
    return cell.value
