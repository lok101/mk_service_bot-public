from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from src.config.settlement import SettlementSettings


def test_settlement_settings_has_no_cron_or_tolerance() -> None:
    settings = SettlementSettings(SETTLEMENT_SALES_COVERAGE_TOLERANCE_SECONDS=900)
    assert not hasattr(settings, "cron_enabled")
    assert not hasattr(settings, "delta_tolerance")
    assert settings.sales_coverage_tolerance_seconds == 900


def test_settlement_settings_has_no_audit_spreadsheet_fields() -> None:
    """happy: spreadsheet/sheet id fields removed."""
    settings = SettlementSettings()
    assert not hasattr(settings, "audit_spreadsheet_id")
    assert not hasattr(settings, "audit_sheet_id")
    assert not hasattr(settings, "audit_warehouse_sheet_id")
    assert not hasattr(settings, "is_audit_configured")
    for name in (
        "audit_spreadsheet_id",
        "audit_sheet_id",
        "audit_warehouse_sheet_id",
    ):
        assert name not in SettlementSettings.model_fields


def test_audit_timezone_default_moscow() -> None:
    """happy: TZ remains for CLI dates."""
    settings = SettlementSettings()
    assert settings.audit_timezone == ZoneInfo("Europe/Moscow")


def test_audit_timezone_invalid() -> None:
    """error: invalid IANA TZ."""
    with pytest.raises(ValidationError, match="timezone"):
        SettlementSettings(audit_timezone="Not/A/Timezone")


def test_settlement_audit_spreadsheet_env_is_ignored_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """edge: leftover prod env must not break Settings."""
    monkeypatch.setenv("SETTLEMENT_AUDIT_SPREADSHEET_ID", "abc")
    monkeypatch.setenv("SETTLEMENT_AUDIT_SHEET_ID", "0")
    monkeypatch.setenv("SETTLEMENT_AUDIT_WAREHOUSE_SHEET_ID", "1")
    settings = SettlementSettings()
    assert not hasattr(settings, "audit_spreadsheet_id")


def test_settlement_settings_has_no_cutover_commands_enabled() -> None:
    """error path / contract: gate field removed after cutover done."""
    settings = SettlementSettings()
    assert not hasattr(settings, "cutover_commands_enabled")
    assert "cutover_commands_enabled" not in SettlementSettings.model_fields


def test_settlement_cutover_env_is_ignored_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """edge: leftover env must not break Settings (extra=ignore)."""
    monkeypatch.setenv("SETTLEMENT_CUTOVER_COMMANDS_ENABLED", "true")
    settings = SettlementSettings()
    assert not hasattr(settings, "cutover_commands_enabled")
