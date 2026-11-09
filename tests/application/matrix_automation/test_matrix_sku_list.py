from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.matrix_sku_catalog import MatrixSkuCatalogEntry
from src.application.matrix_automation.matrix_sku_list import build_matrix_sku_catalog_rows


def test_build_list_rows_merges_ms_and_mongo() -> None:
    ms = {"A": ("Ms A", False), "B": ("Ms B", False)}
    entries = (
        MatrixSkuCatalogEntry(
            product_code="A",
            display_name="Override A",
            capacity=5,
            product_multiplier=Decimal("1.2"),
        ),
    )
    rows = build_matrix_sku_catalog_rows(ms, entries)
    by_code = {r.product_code: r for r in rows}
    assert by_code["A"].display_name == "Override A"
    assert by_code["A"].capacity == 5
    assert by_code["B"].display_name == "Ms B"
    assert by_code["B"].capacity is None
    assert by_code["B"].product_multiplier == Decimal("1")


def test_build_list_rows_sorts_zero_capacity_first() -> None:
    ms = {"Z": ("z", False), "A": ("a", False), "M": ("m", False)}
    entries = (
        MatrixSkuCatalogEntry(
            product_code="A",
            display_name="a",
            capacity=5,
            product_multiplier=Decimal("1"),
        ),
        MatrixSkuCatalogEntry(
            product_code="M",
            display_name="m",
            capacity=0,
            product_multiplier=Decimal("1"),
        ),
    )
    rows = build_matrix_sku_catalog_rows(ms, entries)
    codes = [r.product_code for r in rows]
    assert codes.index("M") < codes.index("A")
    assert codes.index("Z") < codes.index("A")


def test_build_list_rows_highlight_zero_capacity() -> None:
    ms = {"A": ("a", False), "B": ("b", False)}
    entries = (
        MatrixSkuCatalogEntry(
            product_code="A",
            display_name="a",
            capacity=0,
            product_multiplier=Decimal("1"),
        ),
    )
    rows = build_matrix_sku_catalog_rows(ms, entries)
    by_code = {r.product_code: r for r in rows}
    assert by_code["A"].needs_capacity_highlight is True
    assert by_code["B"].needs_capacity_highlight is True


def test_build_list_rows_omits_codes_not_in_ms() -> None:
    ms = {"SNACK": ("Snack", False)}
    entries = (
        MatrixSkuCatalogEntry(
            product_code="COFFEE",
            display_name="Coffee leftover",
            capacity=5,
            product_multiplier=Decimal("1"),
        ),
        MatrixSkuCatalogEntry(
            product_code="SNACK",
            display_name="Snack overlay",
            capacity=2,
            product_multiplier=Decimal("1"),
        ),
    )
    rows = build_matrix_sku_catalog_rows(ms, entries)
    codes = {r.product_code for r in rows}
    assert codes == {"SNACK"}
    assert all(r.product_code != "COFFEE" for r in rows)


def test_build_list_rows_sets_is_archived() -> None:
    """happy: is_archived берётся из MS map."""
    ms = {"A": ("Active", False), "Z": ("Archived", True)}
    rows = build_matrix_sku_catalog_rows(ms, ())
    by_code = {r.product_code: r for r in rows}
    assert by_code["A"].is_archived is False
    assert by_code["Z"].is_archived is True


def test_build_list_rows_sorts_archived_below_active_needs_capacity() -> None:
    """edge: архив с capacity None ниже активного с capacity 0."""
    ms = {
        "ARCH": ("Archived none", True),
        "ZERO": ("Active zero", False),
        "OK": ("Active ok", False),
    }
    entries = (
        MatrixSkuCatalogEntry(
            product_code="ZERO",
            display_name="Active zero",
            capacity=0,
            product_multiplier=Decimal("1"),
        ),
        MatrixSkuCatalogEntry(
            product_code="OK",
            display_name="Active ok",
            capacity=5,
            product_multiplier=Decimal("1"),
        ),
    )
    rows = build_matrix_sku_catalog_rows(ms, entries)
    codes = [r.product_code for r in rows]
    # active needs_capacity first, then other active, then archived
    assert codes == ["ZERO", "OK", "ARCH"]
    assert rows[-1].is_archived is True
    assert rows[0].needs_capacity_highlight is True
