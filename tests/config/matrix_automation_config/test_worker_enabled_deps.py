from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from src.config.kitvending import KitVendingSettings
from src.config.matrix_automation import MatrixAutomationSettings
from src.config.moysklad import MoySkladSettings
from src.config.settings import Settings, validate_matrix_worker_settings
from src.config.telegram import TelegramSettings

from .fakes import _google_forms_stub, _worker_settings


def _write_valid_platform_accounts(path: Path) -> None:
    from tests.infrastructure.kitvending.platform_account_helpers import (
        platform_account_row,
        write_platform_accounts_file,
    )

    write_platform_accounts_file(path, platform_account_row())


def test_enabled_worker_requires_matrix_moysklad_kit_and_telegram_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATRIX_WORKER_ENABLED", "true")
    with pytest.raises(ValidationError):
        MatrixAutomationSettings()

    with pytest.raises(ValueError, match="MOYSKLAD_API_TOKEN"):
        validate_matrix_worker_settings(_worker_settings())

    accounts_path = tmp_path / "kit_platform_accounts.json"
    _write_valid_platform_accounts(accounts_path)
    with pytest.raises(ValueError, match="TELEGRAM_ALERT_CHAT_ID"):
        validate_matrix_worker_settings(
            _worker_settings(
                moysklad=MoySkladSettings.model_construct(
                    api_token=SecretStr("ms-token"),
                ),
                kitvending=KitVendingSettings.model_construct(accounts_path=accounts_path),
                telegram=TelegramSettings.model_construct(
                    bot_token=SecretStr("test-bot-token"),
                    alert_chat_id=None,
                ),
            ),
        )

    complete = _worker_settings(
        moysklad=MoySkladSettings.model_construct(
            api_token=SecretStr("ms-token"),
            main_store_id="11111111-1111-1111-1111-111111111111",
        ),
        kitvending=KitVendingSettings.model_construct(accounts_path=accounts_path),
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=12345,
        ),
    )
    validate_matrix_worker_settings(complete)
    assert complete.matrix_automation.worker_enabled is True
    assert complete.moysklad.is_configured is True
    assert complete.kitvending.is_configured is True
    assert complete.telegram.alert_chat_id == 12345


def test_enabled_worker_rejects_invalid_kit_accounts_file(tmp_path: Path) -> None:
    accounts_path = tmp_path / "kitvending_accounts.json"
    accounts_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="KIT_PLATFORM_ACCOUNTS_PATH"):
        validate_matrix_worker_settings(
            _worker_settings(
                moysklad=MoySkladSettings.model_construct(
                    api_token=SecretStr("ms-token"),
                ),
                kitvending=KitVendingSettings.model_construct(accounts_path=accounts_path),
                telegram=TelegramSettings.model_construct(
                    bot_token=SecretStr("test-bot-token"),
                    alert_chat_id=12345,
                ),
            ),
        )


def test_enabled_worker_rejects_blank_kit_api_base_url(tmp_path: Path) -> None:
    accounts_path = tmp_path / "kit_platform_accounts.json"
    _write_valid_platform_accounts(accounts_path)

    with pytest.raises(ValueError, match="KITVENDING_API_BASE_URL"):
        validate_matrix_worker_settings(
            _worker_settings(
                moysklad=MoySkladSettings.model_construct(
                    api_token=SecretStr("ms-token"),
                ),
                kitvending=KitVendingSettings.model_construct(
                    accounts_path=accounts_path,
                    api_base_url="   ",
                ),
                telegram=TelegramSettings.model_construct(
                    bot_token=SecretStr("test-bot-token"),
                    alert_chat_id=12345,
                ),
            ),
        )


def test_disabled_worker_does_not_require_phase_one_two_or_telegram_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATRIX_WORKER_ENABLED", "false")
    monkeypatch.delenv("MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID", raising=False)
    monkeypatch.delenv("MOYSKLAD_API_TOKEN", raising=False)
    monkeypatch.setenv("KIT_PLATFORM_ACCOUNTS_PATH", "/nonexistent/kit_platform_accounts.json")
    monkeypatch.delenv("TELEGRAM_ALERT_CHAT_ID", raising=False)

    matrix = MatrixAutomationSettings()
    assert matrix.worker_enabled is False
    assert matrix.google_sheets_spreadsheet_id == ""

    settings = Settings.model_construct(
        google_forms=_google_forms_stub(),
        matrix_automation=matrix,
        moysklad=MoySkladSettings.model_construct(api_token=None),
        kitvending=KitVendingSettings.model_construct(
            accounts_path=Path("/nonexistent/kitvending_accounts.json"),
        ),
        telegram=TelegramSettings.model_construct(
            bot_token=SecretStr("test-bot-token"),
            alert_chat_id=None,
        ),
    )
    validate_matrix_worker_settings(settings)
    assert settings.matrix_automation.worker_enabled is False
    assert settings.moysklad.is_configured is False
    assert settings.kitvending.is_configured is False
    assert settings.telegram.alert_chat_id is None
