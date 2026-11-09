from __future__ import annotations

from decimal import Decimal

from src.application.micromarket_loading.form_fingerprint import (
    INVENTORY_FORM_LAYOUT_SALT,
    inventory_form_fingerprint,
)
from src.application.micromarket_loading.inventory_form_pages import InventoryFormPage
from src.application.micromarket_loading.sku_set import micromarket_inventory_sku_codes
from src.application.product_identity.number import canonical_domain_number
from src.application.snack_loading.form_fingerprint import (
    INVENTORY_FORM_LAYOUT_SALT as snack_salt,
)


def test_inventory_sku_set_includes_off_planogram_stock() -> None:
    codes = micromarket_inventory_sku_codes(
        active_planogram_codes=["d-1"],
        stock_qty={"d-1": Decimal("2"), "d-99": Decimal("1"), "0000": Decimal("0")},
    )
    assert codes == frozenset({"d-1", "d-99"})


def test_inventory_sku_set_excludes_non_number_stock_keys() -> None:
    codes = micromarket_inventory_sku_codes(
        active_planogram_codes=["d-1"],
        stock_qty={"d-1": Decimal("2"), "2311": Decimal("5"), "0000": Decimal("0")},
    )
    assert codes == frozenset({"d-1"})
    assert canonical_domain_number("2311") is None


def test_inventory_sku_set_includes_number_stock_even_if_off_planogram() -> None:
    codes = micromarket_inventory_sku_codes(
        active_planogram_codes=["d-1"],
        stock_qty={"d-1": Decimal("0"), "d-99": Decimal("1")},
    )
    assert codes == frozenset({"d-1", "d-99"})


def test_inventory_sku_set_includes_pending_exit_even_if_inactive() -> None:
    codes = micromarket_inventory_sku_codes(
        active_planogram_codes=["d-1"],
        pending_exit_planogram_codes=["d-2"],
        stock_qty={"d-1": Decimal("0"), "d-2": Decimal("0"), "d-99": Decimal("1")},
    )
    assert codes == frozenset({"d-1", "d-2", "d-99"})


def test_inventory_sku_set_excludes_inactive_without_pending_exit() -> None:
    codes = micromarket_inventory_sku_codes(
        active_planogram_codes=["d-1"],
        pending_exit_planogram_codes=[],
        stock_qty={"d-1": Decimal("0"), "d-3": Decimal("0")},
    )
    assert codes == frozenset({"d-1"})


def test_fingerprint_shelf_order_changes_hash() -> None:
    """happy: same SKU set, different shelf order → different fingerprint."""
    pages_a = (
        InventoryFormPage(kit_group_id=1, product_codes=("d-1", "d-2"), title="A"),
        InventoryFormPage(kit_group_id=2, product_codes=("d-3",), title="B"),
    )
    pages_b = (
        InventoryFormPage(kit_group_id=2, product_codes=("d-3",), title="B"),
        InventoryFormPage(kit_group_id=1, product_codes=("d-1", "d-2"), title="A"),
    )
    assert inventory_form_fingerprint(pages=pages_a, mode="now") != inventory_form_fingerprint(
        pages=pages_b, mode="now"
    )


def test_fingerprint_ignores_display_title() -> None:
    """edge: rename title with same structure → same hash."""
    a = InventoryFormPage(kit_group_id=1, product_codes=("d-1",), title="Холод")
    b = InventoryFormPage(kit_group_id=1, product_codes=("d-1",), title="Другое имя")
    assert inventory_form_fingerprint(pages=(a,), mode="now") == inventory_form_fingerprint(
        pages=(b,), mode="now"
    )


def test_micromarket_fingerprint_salt_is_shelves_pages_v1() -> None:
    assert INVENTORY_FORM_LAYOUT_SALT == "shelves_pages_v1"
    assert snack_salt == "labels_v2"
    assert snack_salt != INVENTORY_FORM_LAYOUT_SALT
