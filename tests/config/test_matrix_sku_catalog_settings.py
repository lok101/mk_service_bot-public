from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import ValidationError

from src.config.matrix_automation import MatrixAutomationSettings
from src.config.mongodb import MongoSettings
from src.config.settings import sku_catalog_master_dependency_errors

_UID_A = UUID("11111111-1111-1111-1111-111111111111")
_UID_B = UUID("22222222-2222-2222-2222-222222222222")


def test_sku_catalog_master_defaults_false() -> None:
    assert MatrixAutomationSettings().sku_catalog_master_enabled is False


def test_sku_catalog_ms_folder_ids_csv_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MATRIX_SKU_CATALOG_MS_PRODUCT_FOLDER_IDS",
        f" {_UID_A} , , {_UID_B}, {_UID_A} ",
    )
    settings = MatrixAutomationSettings()
    assert settings.sku_catalog_ms_product_folder_ids == (_UID_A, _UID_B)


def test_matrix_sku_catalog_collection_default() -> None:
    assert MongoSettings().matrix_sku_catalog_collection == "matrix_sku_catalog"


def test_matrix_sku_catalog_collection_rejects_blank() -> None:
    with pytest.raises(ValidationError):
        MongoSettings(matrix_sku_catalog_collection="   ")


def test_sku_catalog_master_requires_master_data_and_mongo() -> None:
    errors = sku_catalog_master_dependency_errors(
        sku_catalog_master_enabled=True,
        master_data_enabled=False,
        mongodb_configured=False,
        folder_ids=(_UID_A,),
    )
    assert any("MASTER_DATA_ENABLED" in e for e in errors)
    assert any("MONGODB_URI" in e for e in errors)


def test_sku_catalog_master_requires_each_dep_separately() -> None:
    assert sku_catalog_master_dependency_errors(
        sku_catalog_master_enabled=True,
        master_data_enabled=True,
        mongodb_configured=False,
        folder_ids=(_UID_A,),
    ) == ["MONGODB_URI must be set when MATRIX_SKU_CATALOG_MASTER_ENABLED=true"]
    assert sku_catalog_master_dependency_errors(
        sku_catalog_master_enabled=True,
        master_data_enabled=False,
        mongodb_configured=True,
        folder_ids=(_UID_A,),
    ) == ["MASTER_DATA_ENABLED must be true when MATRIX_SKU_CATALOG_MASTER_ENABLED=true"]


def test_sku_catalog_master_off_allows_missing_master() -> None:
    assert (
        sku_catalog_master_dependency_errors(
            sku_catalog_master_enabled=False,
            master_data_enabled=False,
            mongodb_configured=False,
        )
        == []
    )


def test_sku_catalog_master_requires_snack_folder_ids() -> None:
    errs = sku_catalog_master_dependency_errors(
        sku_catalog_master_enabled=True,
        master_data_enabled=True,
        mongodb_configured=True,
        folder_ids=(),
    )
    assert any("MATRIX_SKU_CATALOG_MS_PRODUCT_FOLDER_IDS" in e for e in errs)


def test_sku_catalog_snack_folder_ids_optional_when_flag_off() -> None:
    assert (
        sku_catalog_master_dependency_errors(
            sku_catalog_master_enabled=False,
            master_data_enabled=False,
            mongodb_configured=False,
            folder_ids=(),
        )
        == []
    )


def test_sku_catalog_master_independent_of_layout_and_worker() -> None:
    """Flag on + MASTER_DATA + Mongo — OK даже если layout/worker off (helper не смотрит на них)."""
    assert (
        sku_catalog_master_dependency_errors(
            sku_catalog_master_enabled=True,
            master_data_enabled=True,
            mongodb_configured=True,
            folder_ids=(_UID_A,),
        )
        == []
    )


def test_settings_rejects_sku_catalog_without_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.config.settings import Settings

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
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("MATRIX_SKU_CATALOG_MASTER_ENABLED", "true")
    monkeypatch.setenv("MASTER_DATA_ENABLED", "false")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_sku_catalog_without_snack_folder_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.config.settings import Settings

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
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("MASTER_DATA_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "mk_bot")
    monkeypatch.setenv("MONGODB_URI", "mongodb://localhost:27017/test")
    monkeypatch.setenv("MATRIX_SKU_CATALOG_MASTER_ENABLED", "true")
    monkeypatch.setenv("MATRIX_SKU_CATALOG_MS_PRODUCT_FOLDER_IDS", "")
    with pytest.raises(ValidationError, match="MATRIX_SKU_CATALOG_MS_PRODUCT_FOLDER_IDS"):
        Settings()
