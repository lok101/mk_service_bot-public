from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from src.config.location_roster import LocationRosterSettings
from src.config.settings import Settings
from src.config.telegram import TelegramSettings


def test_location_roster_defaults_disabled() -> None:
    settings = LocationRosterSettings()
    assert settings.enabled is False
    assert settings.session_ttl_seconds == 86400
    assert settings.telegram_auth_max_age_seconds == 86400
    assert settings.dev_stub_login_enabled is False
    assert settings.roster_collection == "location_roster"
    assert settings.audit_collection == "location_roster_audit"
    assert settings.telegram_bot_username == ""


def test_location_roster_draft_collection_default() -> None:
    settings = LocationRosterSettings()
    assert settings.draft_collection == "location_roster_draft"


def test_enabled_without_session_secret_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "mk_bot")
    with pytest.raises(ValidationError):
        LocationRosterSettings()


def test_enabled_without_bot_username_raises_when_stub_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "false")
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    with pytest.raises(ValidationError):
        LocationRosterSettings()


def test_enabled_with_stub_does_not_require_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    settings = LocationRosterSettings()
    assert settings.enabled is True
    assert settings.dev_stub_login_enabled is True


def test_bot_username_rejects_leading_at(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@mk_bot")
    with pytest.raises(ValidationError):
        LocationRosterSettings()


def test_ttl_below_sixty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_SESSION_TTL_SECONDS", "59")
    with pytest.raises(ValidationError):
        LocationRosterSettings()


def test_max_age_below_sixty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_TELEGRAM_AUTH_MAX_AGE_SECONDS", "0")
    with pytest.raises(ValidationError):
        LocationRosterSettings()


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
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)


def test_stub_login_with_webhook_ip_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    with pytest.raises(ValidationError, match="ADMIN_DEV_STUB_LOGIN_ENABLED"):
        Settings(
            telegram=TelegramSettings(
                BOT_TOKEN=SecretStr("token"),
                TELEGRAM_WEBHOOK_IP="bot.example.com",
            ),
        )


def test_stub_login_without_webhook_ip_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    settings = Settings(
        telegram=TelegramSettings(
            BOT_TOKEN=SecretStr("token"),
            TELEGRAM_WEBHOOK_IP="",
        ),
    )
    assert settings.location_roster.dev_stub_login_enabled is True
    assert settings.telegram.uses_webhook is False


def test_stub_login_forbidden_when_environment_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_required_app_env(monkeypatch)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("LOCATION_ROSTER_ENABLED", "true")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("ADMIN_DEV_STUB_LOGIN_ENABLED", "true")
    monkeypatch.delenv("TELEGRAM_WEBHOOK_IP", raising=False)
    with pytest.raises(ValidationError, match="ADMIN_DEV_STUB_LOGIN_ENABLED"):
        Settings(
            telegram=TelegramSettings(
                BOT_TOKEN=SecretStr("token"),
                TELEGRAM_WEBHOOK_IP="",
            ),
        )
