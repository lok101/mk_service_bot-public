from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.matrix_automation import MatrixAutomationSettings


def test_spreadsheet_requires_utility_sheet_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID", "sheet-id")
    with pytest.raises(ValidationError):
        MatrixAutomationSettings()


def test_matrix_settings_without_products_sheet_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """happy: spreadsheet + multipliers GID без PRODUCTS/BASE_MARGIN/STREAM → settings ок."""
    monkeypatch.setenv("MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID", "sheet-id")
    monkeypatch.setenv("MATRIX_PRODUCT_MULTIPLIERS_SHEET_ID", "2")
    monkeypatch.delenv("MATRIX_PRODUCTS_SHEET_ID", raising=False)
    monkeypatch.delenv("MATRIX_BASE_MARGIN_SHEET_ID", raising=False)
    monkeypatch.delenv("MATRIX_PRICE_CHANGE_STREAM_SHEET_ID", raising=False)
    settings = MatrixAutomationSettings()
    assert "products_sheet_id" not in MatrixAutomationSettings.model_fields
    assert "base_margin_sheet_id" not in MatrixAutomationSettings.model_fields
    assert "price_change_stream_sheet_id" not in MatrixAutomationSettings.model_fields
    assert settings.product_multipliers_sheet_id == 2


def test_spreadsheet_accepts_multipliers_without_stream_sheet_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """happy: spreadsheet + multipliers без stream GID → settings ок."""
    monkeypatch.setenv("MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID", "sheet-id")
    monkeypatch.setenv("MATRIX_PRODUCT_MULTIPLIERS_SHEET_ID", "3")
    monkeypatch.delenv("MATRIX_PRICE_CHANGE_STREAM_SHEET_ID", raising=False)
    monkeypatch.delenv("MATRIX_BASE_MARGIN_SHEET_ID", raising=False)
    settings = MatrixAutomationSettings()
    assert settings.product_multipliers_sheet_id == 3
    assert not hasattr(settings, "price_change_stream_sheet_id")


def test_phase2_defaults_are_valid() -> None:
    settings = MatrixAutomationSettings()
    assert settings.load_timeout_seconds == 300
    assert settings.apply_timeout_seconds == 300
    assert settings.status_poll_interval_seconds == 15
    assert settings.command_send_delay_seconds == 7
    assert settings.poll_api_max_retries == 10
    assert settings.retry_send_command_delay_seconds == 10
    assert settings.blocking_cell_label == "БЛОК"


@pytest.mark.parametrize(
    "env_var",
    [
        "MATRIX_LOAD_TIMEOUT_SECONDS",
        "MATRIX_APPLY_TIMEOUT_SECONDS",
        "MATRIX_STATUS_POLL_INTERVAL_SECONDS",
        "MATRIX_COMMAND_SEND_DELAY_SECONDS",
        "MATRIX_POLL_API_MAX_RETRIES",
        "MATRIX_RETRY_SEND_COMMAND_DELAY_SECONDS",
    ],
)
def test_phase2_int_settings_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
) -> None:
    monkeypatch.setenv(env_var, "0")
    with pytest.raises(ValidationError):
        MatrixAutomationSettings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MATRIX_WORKER_CRON_HOUR", "-1"),
        ("MATRIX_WORKER_CRON_HOUR", "24"),
    ],
)
def test_worker_cron_hour_requires_0_to_23(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        MatrixAutomationSettings()
