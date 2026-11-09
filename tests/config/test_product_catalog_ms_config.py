from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from src.config.product_catalog_ms import ProductCatalogMsSettings

_UID_A = UUID("11111111-1111-1111-1111-111111111111")
_UID_B = UUID("22222222-2222-2222-2222-222222222222")


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


def test_settings_without_bundle_path_names_field() -> None:
    assert "bundle_path_names" not in ProductCatalogMsSettings.model_fields


def test_defaults_disabled_are_valid() -> None:
    settings = ProductCatalogMsSettings()
    assert settings.sync_enabled is False
    assert settings.product_folder_ids == ()
    assert settings.sync_interval_seconds == 3600
    assert settings.staleness_alert_seconds == 7200


def test_folder_ids_csv_parsed_and_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS",
        f" {_UID_A} , {_UID_B}, {_UID_A} ",
    )
    settings = ProductCatalogMsSettings()
    assert settings.product_folder_ids == (_UID_A, _UID_B)


def test_folder_ids_reject_non_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS", "not-a-uuid")
    with pytest.raises(ValidationError):
        ProductCatalogMsSettings()


def test_staleness_must_not_be_below_sync_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODUCT_CATALOG_MS_SYNC_INTERVAL_SECONDS", "3600")
    monkeypatch.setenv("PRODUCT_CATALOG_MS_STALENESS_ALERT_SECONDS", "100")
    with pytest.raises(ValidationError):
        ProductCatalogMsSettings()


def test_nested_allows_enabled_without_token_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token/folder-ids-when-enabled — в validate_product_catalog_ms_settings, не в nested."""
    monkeypatch.setenv("PRODUCT_CATALOG_MS_SYNC_ENABLED", "true")
    monkeypatch.setenv("PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS", str(_UID_A))
    monkeypatch.delenv("MOYSKLAD_API_TOKEN", raising=False)
    settings = ProductCatalogMsSettings()
    assert settings.sync_enabled is True


def test_enabled_requires_product_folder_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.settings import Settings, validate_product_catalog_ms_settings

    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("PRODUCT_CATALOG_MS_SYNC_ENABLED", "true")
    monkeypatch.setenv("MOYSKLAD_API_TOKEN", "token")
    monkeypatch.setenv("PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS", "")
    with pytest.raises(ValueError, match="PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS"):
        validate_product_catalog_ms_settings(Settings())


def test_enabled_requires_moysklad_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config.settings import Settings, validate_product_catalog_ms_settings

    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("PRODUCT_CATALOG_MS_SYNC_ENABLED", "true")
    monkeypatch.setenv("PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS", str(_UID_A))
    monkeypatch.delenv("MOYSKLAD_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="MOYSKLAD_API_TOKEN"):
        validate_product_catalog_ms_settings(Settings())


def test_enabled_with_token_and_product_folder_ids_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.settings import Settings, validate_product_catalog_ms_settings

    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("PRODUCT_CATALOG_MS_SYNC_ENABLED", "true")
    monkeypatch.setenv("MOYSKLAD_API_TOKEN", "token")
    monkeypatch.setenv("PRODUCT_CATALOG_MS_PRODUCT_FOLDER_IDS", str(_UID_A))
    settings = Settings()
    validate_product_catalog_ms_settings(settings)  # no raise
    assert settings.product_catalog_ms.sync_enabled is True
    assert settings.product_catalog_ms.product_folder_ids == (_UID_A,)
    assert settings.moysklad.is_configured is True
