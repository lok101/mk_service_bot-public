from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.master_data import MasterDataSettings
from src.config.settings import Settings


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
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)


def test_master_data_defaults_disabled() -> None:
    settings = MasterDataSettings()
    assert settings.enabled is False
    assert settings.sheets_export_enabled is False
    assert settings.locations_collection == "master_locations"
    assert settings.machines_collection == "master_machines"
    assert settings.placements_collection == "master_placements"
    assert settings.counters_collection == "master_data_counters"
    assert settings.audit_collection == "master_data_audit"
    assert settings.telegram_bot_username == ""


def test_master_data_mirror_defaults() -> None:
    settings = MasterDataSettings()
    assert settings.sheets_export_enabled is False
    assert settings.mirror_spreadsheet_id == ""
    assert settings.mirror_locations_sheet_id is None
    assert settings.mirror_machines_sheet_id is None


def test_users_defaults_disabled() -> None:
    settings = MasterDataSettings()
    assert settings.users_enabled is False
    assert settings.system_users_collection == "master_system_users"


def test_technicians_defaults_disabled() -> None:
    settings = MasterDataSettings()
    assert settings.technicians_enabled is False
    assert settings.technicians_collection == "master_technicians"


def test_users_enabled_without_session_secret_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASTER_DATA_USERS_ENABLED", "true")
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "mk_bot")
    with pytest.raises(ValidationError):
        MasterDataSettings()


def test_users_enabled_with_stub_does_not_require_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASTER_DATA_USERS_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    settings = MasterDataSettings()
    assert settings.users_enabled is True


def test_technicians_enabled_without_session_secret_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASTER_DATA_TECHNICIANS_ENABLED", "true")
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "mk_bot")
    with pytest.raises(ValidationError):
        MasterDataSettings()


def test_technicians_enabled_with_stub_does_not_require_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASTER_DATA_TECHNICIANS_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    settings = MasterDataSettings()
    assert settings.technicians_enabled is True


def test_users_enabled_still_requires_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASTER_DATA_USERS_ENABLED", "true")
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "mk_bot")
    with pytest.raises(ValidationError):
        MasterDataSettings()


def test_park_enabled_still_requires_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Регрессия: MASTER_DATA_ENABLED=true без secret по-прежнему ValidationError."""
    monkeypatch.setenv("MASTER_DATA_ENABLED", "true")
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "mk_bot")
    with pytest.raises(ValidationError):
        MasterDataSettings()


def test_enabled_without_session_secret_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASTER_DATA_ENABLED", "true")
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "mk_bot")
    with pytest.raises(ValidationError):
        MasterDataSettings()


def test_enabled_without_bot_username_raises_when_stub_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASTER_DATA_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "false")
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    with pytest.raises(ValidationError):
        MasterDataSettings()


def test_enabled_with_stub_does_not_require_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MASTER_DATA_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    settings = MasterDataSettings()
    assert settings.enabled is True


def test_bot_username_rejects_leading_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTER_DATA_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@mk_bot")
    with pytest.raises(ValidationError):
        MasterDataSettings()


def test_settings_nested_master_data_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    settings = Settings()
    assert settings.master_data.enabled is False
    assert settings.master_data.sheets_export_enabled is False


def test_export_enabled_requires_mirror_triad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("MASTER_DATA_SHEETS_EXPORT_ENABLED", "true")
    monkeypatch.delenv("MASTER_DATA_MIRROR_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("MASTER_DATA_MIRROR_LOCATIONS_SHEET_ID", raising=False)
    monkeypatch.delenv("MASTER_DATA_MIRROR_MACHINES_SHEET_ID", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_export_enabled_ok_with_mirror_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("MASTER_DATA_SHEETS_EXPORT_ENABLED", "true")
    monkeypatch.setenv("MASTER_DATA_MIRROR_SPREADSHEET_ID", "mirror-book")
    monkeypatch.setenv("MASTER_DATA_MIRROR_LOCATIONS_SHEET_ID", "11")
    monkeypatch.setenv("MASTER_DATA_MIRROR_MACHINES_SHEET_ID", "12")
    # park/directory намеренно НЕ задаём
    monkeypatch.delenv("COFFEE_TECHNICIAN_LOCATIONS_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("COFFEE_TECHNICIAN_LOCATIONS_SHEET_ID", raising=False)
    monkeypatch.delenv("SNACK_TECHNICIAN_LOCATIONS_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("SNACK_TECHNICIAN_LOCATIONS_SHEET_ID", raising=False)
    monkeypatch.delenv("LOCATIONS_DIRECTORY_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("LOCATIONS_DIRECTORY_SHEET_ID", raising=False)
    monkeypatch.delenv("USERS_SHEET_ID", raising=False)
    settings = Settings()
    assert settings.master_data.sheets_export_enabled is True
    assert settings.master_data.mirror_spreadsheet_id == "mirror-book"
    assert settings.master_data.mirror_locations_sheet_id == 11
    assert settings.master_data.mirror_machines_sheet_id == 12
