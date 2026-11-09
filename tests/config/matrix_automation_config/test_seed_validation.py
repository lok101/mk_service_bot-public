from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from src.config.kitvending import KitVendingSettings
from src.config.moysklad import MoySkladSettings
from src.config.settings import (
    matrix_runtime_dependency_errors,
    validate_matrix_seed_settings,
)
from src.config.telegram import TelegramSettings

from .fakes import _complete_matrix_runtime_settings, _complete_seed_settings


def test_matrix_runtime_dependency_errors_empty_when_stack_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _complete_matrix_runtime_settings(tmp_path, monkeypatch)
    assert matrix_runtime_dependency_errors(settings, when="MATRIX_WORKER_ENABLED=true") == []


def test_validate_matrix_seed_settings_rejects_when_worker_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """error: ENABLED=true → fail-fast."""
    settings = _complete_seed_settings(tmp_path, monkeypatch, worker_enabled=True)
    with pytest.raises(ValueError, match="MATRIX_WORKER_ENABLED"):
        validate_matrix_seed_settings(settings)


def test_validate_matrix_seed_settings_requires_sheets_and_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """error: ENABLED=false без spreadsheet / sheet ids / credentials file."""
    settings = _complete_seed_settings(tmp_path, monkeypatch, worker_enabled=False)
    settings.matrix_automation.google_sheets_spreadsheet_id = ""
    with pytest.raises(ValueError, match="MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID|credentials|sheet"):
        validate_matrix_seed_settings(settings)


def test_validate_matrix_seed_settings_requires_existing_credentials_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """error: путь credentials задан, файла нет."""
    settings = _complete_seed_settings(tmp_path, monkeypatch, worker_enabled=False)
    settings.google_sheets.credentials_file = str(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="GOOGLE_SERVICE_ACCOUNT_CREDENTIALS_FILE|credentials"):
        validate_matrix_seed_settings(settings)


def test_validate_matrix_seed_settings_ok_with_full_stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """happy: ENABLED=false + полный stack → без исключения."""
    settings = _complete_seed_settings(tmp_path, monkeypatch, worker_enabled=False)
    validate_matrix_seed_settings(settings)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        (
            "moysklad",
            MoySkladSettings.model_construct(api_token=None),
            "MOYSKLAD_API_TOKEN",
        ),
        (
            "telegram",
            TelegramSettings.model_construct(
                bot_token=SecretStr("test-bot-token"),
                alert_chat_id=None,
            ),
            "TELEGRAM_ALERT_CHAT_ID",
        ),
    ],
)
def test_validate_matrix_seed_settings_rejects_incomplete_runtime_stack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    match: str,
) -> None:
    """error: ENABLED=false, Sheets ok, но неполный MS/Kit/Telegram → fail-fast."""
    settings = _complete_seed_settings(tmp_path, monkeypatch, worker_enabled=False)
    settings = settings.model_copy(update={field: value})
    with pytest.raises(ValueError, match=match):
        validate_matrix_seed_settings(settings)


def test_validate_matrix_seed_settings_rejects_invalid_kit_accounts_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """error: seed rejects invalid Kit accounts JSON."""
    settings = _complete_seed_settings(tmp_path, monkeypatch, worker_enabled=False)
    accounts_path = tmp_path / "invalid_kitvending_accounts.json"
    accounts_path.write_text("{not-json", encoding="utf-8")
    settings = settings.model_copy(
        update={
            "kitvending": KitVendingSettings.model_construct(accounts_path=accounts_path),
        },
    )
    with pytest.raises(ValueError, match="KIT_PLATFORM_ACCOUNTS_PATH"):
        validate_matrix_seed_settings(settings)


@pytest.mark.parametrize(
    "field",
    [
        "product_multipliers_sheet_id",
    ],
)
def test_validate_matrix_seed_settings_requires_utility_sheet_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    """error: MATRIX_*_SHEET_ID must be set for matrix seed."""
    settings = _complete_seed_settings(tmp_path, monkeypatch, worker_enabled=False)
    setattr(settings.matrix_automation, field, None)
    with pytest.raises(ValueError, match="SHEET_ID must be set for matrix seed"):
        validate_matrix_seed_settings(settings)


def test_matrix_seed_does_not_require_products_sheet_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """После cutover seed не ссылается на MATRIX_PRODUCTS_SHEET_ID."""
    settings = _complete_seed_settings(tmp_path, monkeypatch, worker_enabled=False)
    validate_matrix_seed_settings(settings)
