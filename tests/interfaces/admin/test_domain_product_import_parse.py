from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from src.application.product_identity import (
    FILE_EMPTY_TEXT,
    FILE_UNREADABLE_TEXT,
    DomainProductImportRow,
)
from src.interfaces.admin.domain_product_import_parse import (
    DomainProductImportParseError,
    parse_domain_product_import_file,
)

_FIXTURES = Path(__file__).parent / "fixtures"


def _xlsx_bytes(rows: list[list[object]]) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_parse_csv_utf8_skips_header() -> None:
    raw = "name,code\nМолоко,2311\nЧай,\n".encode()
    rows = parse_domain_product_import_file(raw, filename="goods.csv")
    assert [(row.line_number, row.name, row.catalog_code) for row in rows] == [
        (2, "Молоко", "2311"),
        (3, "Чай", ""),
    ]


def test_parse_csv_semicolon_cp1251_skips_header() -> None:
    raw = "имя;код\nМолоко;2311\n".encode("cp1251")
    rows = parse_domain_product_import_file(raw, filename="goods.CSV")
    assert rows == (DomainProductImportRow(line_number=2, name="Молоко", catalog_code="2311"),)


def test_parse_csv_bom_utf8() -> None:
    raw = "\ufeffname,code\nМолоко,\n".encode()
    rows = parse_domain_product_import_file(raw, filename="a.csv")
    assert rows[0].name == "Молоко"
    assert rows[0].catalog_code == ""


def test_parse_ignores_extra_columns() -> None:
    raw = "a,b,c\nМолоко,2311,extra\n".encode()
    rows = parse_domain_product_import_file(raw, filename="a.csv")
    assert rows[0].catalog_code == "2311"


def test_parse_skips_blank_data_rows() -> None:
    raw = "a,b\n\n  ,  \nМолоко,\n".encode()
    rows = parse_domain_product_import_file(raw, filename="a.csv")
    assert len(rows) == 1
    assert rows[0].line_number == 4


def test_parse_csv_equal_comma_and_semicolon_uses_comma() -> None:
    raw = "a,b;c\nМолоко,2311\n".encode()
    rows = parse_domain_product_import_file(raw, filename="a.csv")
    assert rows[0].name == "Молоко"
    assert rows[0].catalog_code == "2311"


def test_parse_csv_no_comma_or_semicolon_uses_comma() -> None:
    raw = "name\nМолоко\n".encode()
    rows = parse_domain_product_import_file(raw, filename="a.csv")
    assert rows == (DomainProductImportRow(line_number=2, name="Молоко", catalog_code=""),)


def test_parse_header_only_empty_file() -> None:
    raw = b"name,code\n\n"
    with pytest.raises(DomainProductImportParseError, match=FILE_EMPTY_TEXT):
        parse_domain_product_import_file(raw, filename="a.csv")


def test_parse_unknown_extension_unreadable() -> None:
    with pytest.raises(DomainProductImportParseError, match=FILE_UNREADABLE_TEXT):
        parse_domain_product_import_file(b"x", filename="a.txt")


def test_parse_corrupt_bytes_unreadable() -> None:
    with pytest.raises(DomainProductImportParseError, match=FILE_UNREADABLE_TEXT):
        parse_domain_product_import_file(b"\x00\x01\x02not-a-book", filename="a.xlsx")


def test_parse_xlsx_integer_float_without_dot_zero() -> None:
    raw = _xlsx_bytes([["name", "code"], ["Молоко", 12345.0]])
    rows = parse_domain_product_import_file(raw, filename="a.xlsx")
    assert rows[0].catalog_code == "12345"
    assert rows[0].name == "Молоко"


def test_parse_xlsx_fraction_without_exponent() -> None:
    raw = _xlsx_bytes([["n", "c"], ["Товар", 1.5]])
    rows = parse_domain_product_import_file(raw, filename="a.xlsx")
    assert rows[0].catalog_code == "1.5"


def test_parse_xls_reads_first_sheet() -> None:
    raw = (_FIXTURES / "domain_product_import_sample.xls").read_bytes()
    rows = parse_domain_product_import_file(raw, filename="sample.xls")
    assert rows[0].line_number == 2
    assert rows[0].name == "Молоко"
    assert rows[0].catalog_code == "2311"
