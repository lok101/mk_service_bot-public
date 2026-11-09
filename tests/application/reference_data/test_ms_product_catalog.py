from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.application.reference_data.ms_product_catalog import (
    MsEntityKind,
    MsProductCatalogParseError,
    MsProductEntry,
    build_ms_catalog_snapshot_rows,
    parse_ms_product_catalog_rows,
)


def test_ms_product_entry_archived_defaults_false() -> None:
    """happy: call sites без archived остаются активными."""
    entry = MsProductEntry(
        code="p1",
        name="One",
        entity_kind=MsEntityKind.PRODUCT,
    )
    assert entry.archived is False


def test_parse_ms_rows_archived_defaults_false() -> None:
    """edge: sheet parse без колонки archived → False."""
    parsed = parse_ms_product_catalog_rows(
        [
            ["code", "name", "entity_kind"],
            ["p1", "Product One", "product"],
        ],
    )
    assert parsed.by_code["p1"].archived is False


def test_build_ms_catalog_snapshot_rows_keeps_archived() -> None:
    rows = build_ms_catalog_snapshot_rows(
        [
            MsProductEntry(
                code="a",
                name="Arch",
                entity_kind=MsEntityKind.PRODUCT,
                archived=True,
            ),
            MsProductEntry(
                code="b",
                name="Live",
                entity_kind=MsEntityKind.PRODUCT,
                archived=False,
            ),
        ],
    )
    assert rows[0] == ["code", "name", "entity_kind", "archived"]
    assert rows[1] == ["a", "Arch", "product", "true"]
    assert rows[2] == ["b", "Live", "product", "false"]


def test_parse_ms_rows_reads_archived_column() -> None:
    parsed = parse_ms_product_catalog_rows(
        [
            ["code", "name", "entity_kind", "archived"],
            ["a", "Arch", "product", "true"],
            ["b", "Live", "bundle", "false"],
        ],
    )
    assert parsed.by_code["a"].archived is True
    assert parsed.by_code["b"].archived is False


def test_parse_ms_rows_rejects_bad_archived() -> None:
    rows = [
        ["code", "name", "entity_kind", "archived"],
        ["a", "Arch", "product", "yes"],
    ]
    with pytest.raises(MsProductCatalogParseError, match="bad archived"):
        parse_ms_product_catalog_rows(rows)


def test_product_catalog_sync_does_not_reference_domain_products() -> None:
    text = Path("src/application/reference_data/sync_product_catalog_ms.py").read_text(
        encoding="utf-8",
    )
    assert "domain_product" not in text
    assert "product_identity" not in text


def test_parse_ms_rows_happy() -> None:
    rows = [
        ["code", "name", "entity_kind"],
        [" p1 ", " Product One ", "product"],
        ["b1", "Bundle One", "bundle"],
    ]
    parsed = parse_ms_product_catalog_rows(rows)
    assert parsed.by_code["p1"].name == "Product One"
    assert parsed.by_code["p1"].entity_kind is MsEntityKind.PRODUCT
    assert parsed.name_to_code["Product One"] == "p1"
    assert " product one " not in parsed.name_to_code  # no casefold key
    assert parsed.name_to_code.get("Product One ".strip()) == "p1"


def test_parse_ms_skips_empty_code(caplog: pytest.LogCaptureFixture) -> None:
    rows = [
        ["code", "name", "entity_kind"],
        ["", "NoCode", "product"],
        ["ok", "Ok", "product"],
    ]
    with caplog.at_level(logging.WARNING):
        parsed = parse_ms_product_catalog_rows(rows)
    assert "ok" in parsed.by_code
    assert "" not in parsed.by_code
    assert any(
        "empty_code" in r.message or "skipped_empty_code" in r.message for r in caplog.records
    )


def test_parse_ms_rejects_duplicate_code() -> None:
    rows = [
        ["code", "name", "entity_kind"],
        ["c1", "A", "product"],
        ["c1", "B", "bundle"],
    ]
    with pytest.raises(MsProductCatalogParseError, match="duplicate code"):
        parse_ms_product_catalog_rows(rows)


def test_parse_ms_rejects_duplicate_name() -> None:
    rows = [
        ["code", "name", "entity_kind"],
        ["c1", "Same", "product"],
        ["c2", "Same", "bundle"],
    ]
    with pytest.raises(MsProductCatalogParseError, match="duplicate name"):
        parse_ms_product_catalog_rows(rows)


def test_parse_ms_rejects_bad_header() -> None:
    with pytest.raises(MsProductCatalogParseError):
        parse_ms_product_catalog_rows([["id", "имя"], ["x", "y"]])
