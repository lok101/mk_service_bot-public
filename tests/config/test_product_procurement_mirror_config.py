from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.product_procurement_mirror import ProductProcurementMirrorSettings


def _stub_required_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_FORMS_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("REVISION_FORM_TOKEN_SECRET", "test-revision-secret")
    monkeypatch.setenv("LOADING_FORM_TOKEN_SECRET", "test-loading-secret")
    monkeypatch.setenv("REVISION_FORM_URL", "https://forms.example/revision")
    monkeypatch.setenv("LOADING_FORM_URL", "https://forms.example/loading")
    monkeypatch.setenv("REVISION_FORM_TOKEN_ENTRY_ID", "entry.1")
    monkeypatch.setenv("LOADING_FORM_TOKEN_ENTRY_ID", "entry.2")
    monkeypatch.setenv("GOOGLE_FORM_TOKEN_FIELD_NAME", "token")
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_URL",
        "https://forms.example/warehouse",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_SECRET",
        "test-warehouse-inventory-secret",
    )
    monkeypatch.setenv(
        "TECHNICIAN_WAREHOUSE_INVENTORY_FORM_TOKEN_ENTRY_ID",
        "entry.3",
    )


def test_procurement_mirror_defaults_disabled() -> None:
    settings = ProductProcurementMirrorSettings()
    assert settings.enabled is False
    assert settings.sync_interval_seconds == 3600
    assert settings.supply_concurrency == 2
    assert settings.collection == "product_procurement_mirror"


def test_procurement_mirror_interval_below_60_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODUCT_PROCUREMENT_MIRROR_SYNC_INTERVAL_SECONDS", "59")
    with pytest.raises(ValidationError):
        ProductProcurementMirrorSettings()


def test_procurement_mirror_concurrency_0_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODUCT_PROCUREMENT_MIRROR_SUPPLY_CONCURRENCY", "0")
    with pytest.raises(ValidationError):
        ProductProcurementMirrorSettings()


def test_procurement_mirror_concurrency_33_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODUCT_PROCUREMENT_MIRROR_SUPPLY_CONCURRENCY", "33")
    with pytest.raises(ValidationError):
        ProductProcurementMirrorSettings()


def _enable_mirror_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCT_PROCUREMENT_MIRROR_ENABLED", "true")
    monkeypatch.setenv("MOYSKLAD_API_TOKEN", "token")
    monkeypatch.setenv("MOYSKLAD_MAIN_STORE_ID", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    monkeypatch.setenv(
        "MOYSKLAD_ATTR_PACKAGE_QUANTITY_ID",
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    monkeypatch.setenv(
        "MOYSKLAD_ATTR_SUPPLIER_PRODUCT_NAME_ID",
        "cccccccc-cccc-cccc-cccc-cccccccccccc",
    )


def test_enabled_without_token_fails_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.settings import Settings, validate_product_procurement_mirror_settings

    _stub_required_app_env(monkeypatch)
    _enable_mirror_base(monkeypatch)
    monkeypatch.delenv("MOYSKLAD_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="MOYSKLAD_API_TOKEN"):
        validate_product_procurement_mirror_settings(Settings())


def test_enabled_with_non_uuid_store_fails_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.settings import Settings, validate_product_procurement_mirror_settings

    _stub_required_app_env(monkeypatch)
    _enable_mirror_base(monkeypatch)
    monkeypatch.setenv("MOYSKLAD_MAIN_STORE_ID", "not-a-uuid")
    with pytest.raises(ValueError, match="MOYSKLAD_MAIN_STORE_ID"):
        validate_product_procurement_mirror_settings(Settings())


def test_enabled_without_attr_uuids_fails_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.settings import Settings, validate_product_procurement_mirror_settings

    _stub_required_app_env(monkeypatch)
    _enable_mirror_base(monkeypatch)
    monkeypatch.delenv("MOYSKLAD_ATTR_PACKAGE_QUANTITY_ID", raising=False)
    with pytest.raises(ValueError, match="MOYSKLAD_ATTR_PACKAGE_QUANTITY_ID"):
        validate_product_procurement_mirror_settings(Settings())


def test_enabled_with_invalid_attr_uuid_fails_validate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.settings import Settings, validate_product_procurement_mirror_settings

    _stub_required_app_env(monkeypatch)
    _enable_mirror_base(monkeypatch)
    monkeypatch.setenv("MOYSKLAD_ATTR_SUPPLIER_PRODUCT_NAME_ID", "not-uuid")
    with pytest.raises(ValueError, match="MOYSKLAD_ATTR_SUPPLIER_PRODUCT_NAME_ID"):
        validate_product_procurement_mirror_settings(Settings())


def test_disabled_skips_token_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config.settings import Settings, validate_product_procurement_mirror_settings

    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("PRODUCT_PROCUREMENT_MIRROR_ENABLED", "false")
    monkeypatch.delenv("MOYSKLAD_API_TOKEN", raising=False)
    validate_product_procurement_mirror_settings(Settings())
