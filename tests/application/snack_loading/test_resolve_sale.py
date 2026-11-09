from __future__ import annotations

from src.application.snack_loading.resolve_sale import resolve_snack_sale


def test_resolve_sale_resolved() -> None:
    status, keys = resolve_snack_sale(
        sale_kind="snack",
        kit_matrix_id=1,
        machine_code="514",
        kit_line_number=3,
        product_code="SKU1",
        deploy_map_row=("SnackA", "514"),
        snapshot_product="SKU1",
    )
    assert status == "resolved"
    assert keys == ("514", "SnackA", 3)


def test_resolve_sale_unresolved_matrix() -> None:
    status, keys = resolve_snack_sale(
        sale_kind="snack",
        kit_matrix_id=1,
        machine_code="514",
        kit_line_number=3,
        product_code="SKU1",
        deploy_map_row=None,
        snapshot_product=None,
    )
    assert status == "unresolved_matrix"
    assert keys is None


def test_resolve_sale_product_mismatch() -> None:
    status, _ = resolve_snack_sale(
        sale_kind="snack",
        kit_matrix_id=1,
        machine_code="514",
        kit_line_number=3,
        product_code="SKU1",
        deploy_map_row=("SnackA", "514"),
        snapshot_product="OTHER",
    )
    assert status == "product_mismatch"


def test_resolve_sale_skipped_non_snack() -> None:
    status, _ = resolve_snack_sale(
        sale_kind="coffee",
        kit_matrix_id=None,
        machine_code="1",
        kit_line_number=1,
        product_code="X",
        deploy_map_row=None,
        snapshot_product=None,
    )
    assert status == "skipped_non_snack"
