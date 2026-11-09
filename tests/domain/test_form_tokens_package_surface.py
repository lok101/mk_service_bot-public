from __future__ import annotations

from importlib import import_module
from pathlib import Path

import src.domain.form_tokens as form_tokens_pkg

_EXPECTED_PUBLIC = {
    "InventoryFormPurpose",
    "RevisionFormTokenPayload",
    "InventoryFormTokenPayload",
    "LoadingFormTokenPayload",
    "MicromarketInventoryFormPurpose",
    "MicromarketInventoryFormTokenPayload",
    "SnackInventoryFormPurpose",
    "SnackInventoryFormTokenPayload",
    "TechnicianWarehouseInventoryTokenPayload",
    "PeekedFormToken",
    "VerifiedInventoryFormToken",
    "PeekedMachineFormToken",
    "create_revision_form_token",
    "verify_revision_form_token",
    "build_verify_revision_form_token",
    "create_loading_form_token",
    "verify_inventory_form_token",
    "build_verify_inventory_form_token",
    "create_technician_warehouse_inventory_token",
    "verify_technician_warehouse_inventory_token",
    "create_snack_inventory_form_token",
    "verify_snack_inventory_form_token",
    "create_micromarket_inventory_form_token",
    "verify_micromarket_inventory_form_token",
    "peek_form_token",
    "peek_machine_form_token",
}


def test_form_tokens_package_public_surface() -> None:
    assert set(form_tokens_pkg.__all__) == _EXPECTED_PUBLIC
    for name in _EXPECTED_PUBLIC:
        assert getattr(form_tokens_pkg, name) is not None


def test_form_tokens_is_package_not_module_file() -> None:
    domain_dir = Path(form_tokens_pkg.__file__).resolve().parent
    assert domain_dir.name == "form_tokens"
    assert (domain_dir / "__init__.py").is_file()
    assert not (domain_dir.parent / "form_tokens.py").exists()
    for leaf in (
        "types",
        "codec",
        "revision",
        "inventory",
        "warehouse",
        "snack_inventory",
        "micromarket_inventory",
        "peek",
    ):
        assert (domain_dir / f"{leaf}.py").is_file()


def test_create_inventory_form_token_lives_in_inventory_not_codec() -> None:
    inventory = import_module("src.domain.form_tokens.inventory")
    codec = import_module("src.domain.form_tokens.codec")
    assert hasattr(inventory, "_create_inventory_form_token")
    assert not hasattr(codec, "_create_inventory_form_token")
