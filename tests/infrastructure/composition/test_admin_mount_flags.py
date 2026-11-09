from __future__ import annotations

import pytest

from src.config.settings import Settings
from src.infrastructure.composition.runtime import admin_ssr_enabled


def _stub_required_app_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "test-bot-token")
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
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)
    monkeypatch.delenv("LOCATION_ROSTER_ENABLED", raising=False)
    monkeypatch.delenv("MASTER_DATA_ENABLED", raising=False)
    monkeypatch.delenv("MASTER_DATA_USERS_ENABLED", raising=False)
    monkeypatch.delenv("MASTER_DATA_TECHNICIANS_ENABLED", raising=False)
    monkeypatch.delenv("MASTER_DATA_COMPANIES_ENABLED", raising=False)


def test_admin_mount_when_technicians_enabled_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MASTER_DATA_TECHNICIANS_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    settings = Settings()
    assert settings.location_roster.enabled is False
    assert settings.master_data.enabled is False
    assert settings.master_data.users_enabled is False
    assert settings.master_data.technicians_enabled is True
    assert admin_ssr_enabled(settings) is True


def test_admin_mount_when_companies_enabled_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("MASTER_DATA_COMPANIES_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    settings = Settings()
    assert settings.master_data.enabled is False
    assert settings.master_data.companies_enabled is True
    assert admin_ssr_enabled(settings) is True
