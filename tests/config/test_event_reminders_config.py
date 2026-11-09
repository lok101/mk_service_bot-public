from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from src.config.event_reminders import EventRemindersSettings
from src.config.google_forms import GoogleFormsSettings
from src.config.google_sheets import GoogleSheetsSettings
from src.config.mongodb import MongoSettings
from src.config.settings import Settings, validate_event_reminders_worker_settings


def test_defaults_worker_disabled() -> None:
    s = EventRemindersSettings()
    assert s.worker_enabled is False
    assert s.tz == "Asia/Yekaterinburg"
    assert s.hours == ()
    assert s.lead_days == ()
    assert s.telegram_bot_token is None
    assert s.telegram_chat_id is None
    assert s.alert_telegram_chat_id is None
    assert s.alert_telegram_bot_token is None
    assert s.spreadsheet_id == ""
    assert s.sheet_id is None


def test_hours_and_lead_days_env_list_trim_unique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EVENT_REMINDERS_HOURS", " 11, 8, 8, ")
    monkeypatch.setenv("EVENT_REMINDERS_LEAD_DAYS", " 3,1,1, ")
    s = EventRemindersSettings()
    assert s.hours == (11, 8)  # unique, first-seen order
    assert s.lead_days == (3, 1)


def test_hours_rejects_out_of_range(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_REMINDERS_HOURS", "24")
    with pytest.raises(ValidationError):
        EventRemindersSettings()


def test_lead_days_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_REMINDERS_LEAD_DAYS", "-1")
    with pytest.raises(ValidationError):
        EventRemindersSettings()


def test_sheet_id_rejects_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_REMINDERS_SHEET_ID", "-1")
    with pytest.raises(ValidationError):
        EventRemindersSettings()


def test_sheet_id_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVENT_REMINDERS_SHEET_ID", "42")
    s = EventRemindersSettings()
    assert s.sheet_id == 42


def _stub_forms() -> GoogleFormsSettings:
    return GoogleFormsSettings.model_construct(
        webhook_secret=SecretStr("test-webhook-secret"),
        revision_form_token_secret=SecretStr("test-revision-secret"),
        loading_form_token_secret=SecretStr("test-loading-secret"),
        revision_form_url="https://forms.example/revision",
        loading_form_url="https://forms.example/loading",
        revision_form_token_entry_id="entry.1",
        loading_form_token_entry_id="entry.2",
        technician_warehouse_inventory_form_url="https://forms.example/warehouse",
        technician_warehouse_inventory_form_token_secret=SecretStr(
            "test-warehouse-inventory-secret",
        ),
        technician_warehouse_inventory_form_token_entry_id="entry.3",
        token_field_name="token",
    )


def _settings(
    *,
    worker_enabled: bool = False,
    telegram_bot_token: str | None = None,
    telegram_chat_id: int | None = None,
    alert_telegram_chat_id: int | None = None,
    spreadsheet_id: str = "",
    sheet_id: int | None = None,
    hours: tuple[int, ...] = (),
    lead_days: tuple[int, ...] = (),
    google_sheets_credentials_file: str = "",
    mongodb_uri: str | None = None,
) -> Settings:
    token = None if telegram_bot_token is None else SecretStr(telegram_bot_token)
    return Settings.model_construct(
        google_forms=_stub_forms(),
        event_reminders=EventRemindersSettings.model_construct(
            worker_enabled=worker_enabled,
            telegram_bot_token=token,
            telegram_chat_id=telegram_chat_id,
            alert_telegram_chat_id=alert_telegram_chat_id,
            spreadsheet_id=spreadsheet_id,
            sheet_id=sheet_id,
            hours=hours,
            lead_days=lead_days,
            tz="Asia/Yekaterinburg",
            alert_telegram_bot_token=None,
        ),
        google_sheets=GoogleSheetsSettings.model_construct(
            credentials_file=google_sheets_credentials_file,
        ),
        mongodb=MongoSettings.model_construct(uri=mongodb_uri),
    )


def test_validate_noop_when_disabled() -> None:
    validate_event_reminders_worker_settings(_settings(worker_enabled=False))


def test_enabled_requires_telegram_and_sheet_not_mongo() -> None:
    s = _settings(
        worker_enabled=True,
        telegram_bot_token=None,
        telegram_chat_id=None,
        alert_telegram_chat_id=None,
        spreadsheet_id="",
        sheet_id=None,
        hours=(),
        lead_days=(),
        mongodb_uri=None,  # must NOT be required
    )
    with pytest.raises(ValueError, match="EVENT_REMINDERS_") as exc_info:
        validate_event_reminders_worker_settings(s)
    msg = str(exc_info.value)
    assert "MONGODB_URI" not in msg
    assert "EVENT_REMINDERS_SHEET_ID" in msg
    assert "SHEET_TITLE" not in msg


def test_enabled_ok_without_mongodb_uri() -> None:
    s = _settings(
        worker_enabled=True,
        telegram_bot_token="tok",
        telegram_chat_id=1,
        alert_telegram_chat_id=2,
        spreadsheet_id="sheet",
        sheet_id=0,
        hours=(8,),
        lead_days=(1,),
        google_sheets_credentials_file="credentials.json",
        mongodb_uri=None,
    )
    validate_event_reminders_worker_settings(s)


def test_equal_report_and_alert_chat_ids_allowed() -> None:
    s = _settings(
        worker_enabled=True,
        telegram_bot_token="tok",
        telegram_chat_id=42,
        alert_telegram_chat_id=42,
        spreadsheet_id="sheet",
        sheet_id=7,
        hours=(8,),
        lead_days=(1,),
        google_sheets_credentials_file="credentials.json",
    )
    validate_event_reminders_worker_settings(s)


def test_enabled_requires_google_sheets_credentials() -> None:
    s = _settings(
        worker_enabled=True,
        telegram_bot_token="tok",
        telegram_chat_id=1,
        alert_telegram_chat_id=2,
        spreadsheet_id="sheet",
        sheet_id=1,
        hours=(8,),
        lead_days=(1,),
        google_sheets_credentials_file="",
    )
    with pytest.raises(ValueError, match="GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE"):
        validate_event_reminders_worker_settings(s)


def test_event_reminders_package_importable() -> None:
    import src.application.event_reminders as er

    assert er.__all__ == ["run_event_reminders_tick"]
    assert er.run_event_reminders_tick is not None
