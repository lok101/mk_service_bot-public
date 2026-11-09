from __future__ import annotations

from src.domain.quantities import QuantityInputMode, mode_from_form_purpose


def test_mode_from_form_purpose_warehouse_inventory_uses_package_count() -> None:
    mode = mode_from_form_purpose("technician_warehouse_inventory")
    assert mode is QuantityInputMode.PACKAGE_COUNT


def test_mode_from_form_purpose_revision_uses_base_stock() -> None:
    assert mode_from_form_purpose("revision") is QuantityInputMode.BASE_STOCK


def test_mode_from_form_purpose_loading_uses_package_count() -> None:
    assert mode_from_form_purpose("loading") is QuantityInputMode.PACKAGE_COUNT
