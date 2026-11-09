from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.matrix_automation import MatrixAutomationSettings
from src.config.mongodb import MongoSettings
from src.config.settings import layout_master_dependency_errors


def test_layout_master_defaults_false() -> None:
    assert MatrixAutomationSettings().layout_master_enabled is False


def test_snack_layouts_collection_default() -> None:
    assert MongoSettings().snack_machine_layouts_collection == "snack_machine_layouts"


def test_snack_layouts_collection_rejects_blank() -> None:
    with pytest.raises(ValidationError):
        MongoSettings(snack_machine_layouts_collection="   ")


def test_layout_master_requires_master_data_and_mongo() -> None:
    errors = layout_master_dependency_errors(
        layout_master_enabled=True,
        master_data_enabled=False,
        mongodb_configured=False,
    )
    assert any("MASTER_DATA_ENABLED" in e for e in errors)
    assert any("MONGODB_URI" in e for e in errors)


def test_layout_master_requires_each_dep_separately() -> None:
    assert layout_master_dependency_errors(
        layout_master_enabled=True,
        master_data_enabled=True,
        mongodb_configured=False,
    ) == ["MONGODB_URI must be set when MATRIX_LAYOUT_MASTER_ENABLED=true"]
    assert layout_master_dependency_errors(
        layout_master_enabled=True,
        master_data_enabled=False,
        mongodb_configured=True,
    ) == ["MASTER_DATA_ENABLED must be true when MATRIX_LAYOUT_MASTER_ENABLED=true"]


def test_layout_master_off_allows_missing_master() -> None:
    assert (
        layout_master_dependency_errors(
            layout_master_enabled=False,
            master_data_enabled=False,
            mongodb_configured=False,
        )
        == []
    )


def test_settings_rejects_layout_master_without_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate живёт на Settings, не только на helper."""
    from src.config.settings import Settings

    # минимальный stub как `_stub_required_app_env` в test_master_data_settings.py
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
    monkeypatch.setenv("MATRIX_LAYOUT_MASTER_ENABLED", "true")
    monkeypatch.setenv("MASTER_DATA_ENABLED", "false")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    with pytest.raises(ValidationError):
        Settings()
