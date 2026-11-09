from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.config.matrix_automation import MatrixAutomationSettings


def test_idle_settings_load_without_sheets_still_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """edge: MatrixAutomationSettings / Settings load при ENABLED=false без spreadsheet."""
    monkeypatch.setenv("MATRIX_WORKER_ENABLED", "false")
    monkeypatch.delenv("MATRIX_GOOGLE_SHEETS_SPREADSHEET_ID", raising=False)
    matrix = MatrixAutomationSettings()
    assert matrix.worker_enabled is False
    assert matrix.google_sheets_spreadsheet_id == ""


def test_defaults_are_valid() -> None:
    settings = MatrixAutomationSettings()
    assert settings.max_price_delta_pct == Decimal("30")
    assert settings.blocking_cell_price == Decimal("999")
    assert settings.product_multiplier_min == Decimal("0.8")
    assert settings.product_multiplier_max == Decimal("3.0")


def test_worker_defaults_are_disabled_and_valid() -> None:
    settings = MatrixAutomationSettings()
    assert settings.worker_enabled is False
    assert settings.worker_cron_hour == 3
    assert settings.kept_alert_pct == Decimal("20")


def test_substitution_guard_is_disabled_by_default() -> None:
    assert MatrixAutomationSettings().substitution_guard_enabled is False


def test_substitution_guard_reads_boolean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIX_SUBSTITUTION_GUARD_ENABLED", "true")
    assert MatrixAutomationSettings().substitution_guard_enabled is True


def test_product_multiplier_bounds_include_one() -> None:
    with pytest.raises(ValidationError):
        MatrixAutomationSettings(
            product_multiplier_min=Decimal("1.1"),
            product_multiplier_max=Decimal("2.0"),
        )


def test_empty_blocking_label_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIX_BLOCKING_CELL_LABEL", "   ")
    with pytest.raises(ValidationError):
        MatrixAutomationSettings()


def test_blocking_cell_label_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MATRIX_BLOCKING_CELL_LABEL", "  БЛОК  ")
    settings = MatrixAutomationSettings()
    assert settings.blocking_cell_label == "БЛОК"
