from __future__ import annotations

from decimal import Decimal

from src.application.matrix_automation.matrix_sku_catalog import (
    DEFAULT_PRODUCT_MULTIPLIER,
    MatrixSkuCatalogEntry,
    is_matrix_ready,
    resolve_product_multiplier,
)


def test_default_product_multiplier_is_one() -> None:
    assert Decimal("1") == DEFAULT_PRODUCT_MULTIPLIER
    assert resolve_product_multiplier(None) == Decimal("1")


def test_is_matrix_ready_true() -> None:
    entry = MatrixSkuCatalogEntry(
        product_code="SKU-1",
        display_name="Chips",
        capacity=10,
        product_multiplier=Decimal("1.2"),
    )
    assert is_matrix_ready(entry) is True


def test_is_matrix_ready_false_capacity() -> None:
    entry = MatrixSkuCatalogEntry(
        product_code="SKU-1",
        display_name="Chips",
        capacity=0,
        product_multiplier=Decimal("1"),
    )
    assert is_matrix_ready(entry) is False


def test_is_matrix_ready_false_empty_name() -> None:
    entry = MatrixSkuCatalogEntry(
        product_code="SKU-1",
        display_name="  ",
        capacity=5,
        product_multiplier=Decimal("1"),
    )
    assert is_matrix_ready(entry) is False


def test_duplicate_display_names_are_distinct_entries() -> None:
    a = MatrixSkuCatalogEntry(
        product_code="A",
        display_name="Same",
        capacity=1,
        product_multiplier=Decimal("1"),
    )
    b = MatrixSkuCatalogEntry(
        product_code="B",
        display_name="Same",
        capacity=2,
        product_multiplier=Decimal("1"),
    )
    assert a.display_name == b.display_name
    assert a.product_code != b.product_code
