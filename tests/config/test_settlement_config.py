from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config.kitvending import KitVendingSettings
from src.config.settlement import SettlementSettings


def test_kitvending_defaults_disabled() -> None:
    settings = KitVendingSettings()
    assert settings.ingestion_enabled is False
    assert settings.poll_interval_seconds == 900


def test_settlement_settings_has_no_cron_or_tolerance() -> None:
    settings = SettlementSettings(SETTLEMENT_SALES_COVERAGE_TOLERANCE_SECONDS=900)
    assert not hasattr(settings, "cron_enabled")
    assert not hasattr(settings, "delta_tolerance")
    assert settings.sales_coverage_tolerance_seconds == 900


def test_settlement_sales_coverage_tolerance_default() -> None:
    settings = SettlementSettings()
    assert settings.sales_coverage_tolerance_seconds == 0


def test_kitvending_is_configured_false_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KIT_PLATFORM_ACCOUNTS_PATH", "/nonexistent/kit_platform_accounts.json")
    settings = KitVendingSettings()
    assert settings.is_configured is False


def test_kitvending_is_configured_true_when_accounts_file_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.infrastructure.kitvending.platform_account_helpers import (
        platform_account_row,
        write_platform_accounts_file,
    )

    accounts_path = tmp_path / "kit_platform_accounts.json"
    write_platform_accounts_file(accounts_path, platform_account_row())
    monkeypatch.setenv("KIT_PLATFORM_ACCOUNTS_PATH", str(accounts_path))
    settings = KitVendingSettings()
    assert settings.is_configured is True
    assert settings.accounts_path == accounts_path


def test_kitvending_is_configured_false_when_accounts_file_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KIT_PLATFORM_ACCOUNTS_PATH", "/nonexistent/kit_platform_accounts.json")
    settings = KitVendingSettings()
    assert settings.is_configured is False


def test_kitvending_require_configured_for_ingestion_raises_when_enabled_but_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SALES_INGESTION_ENABLED", "true")
    monkeypatch.setenv("KIT_PLATFORM_ACCOUNTS_PATH", "/nonexistent/kit_platform_accounts.json")
    settings = KitVendingSettings()
    with pytest.raises(ValueError, match="SALES_INGESTION_ENABLED"):
        settings.require_configured_for_ingestion()


def test_kitvending_require_configured_for_ingestion_ok_when_disabled() -> None:
    KitVendingSettings().require_configured_for_ingestion()


def test_kitvending_is_configured_true_when_accounts_file_exists_even_if_invalid_json(
    tmp_path: Path,
) -> None:
    accounts_path = tmp_path / "kitvending_accounts.json"
    accounts_path.write_text("not-json", encoding="utf-8")
    settings = KitVendingSettings.model_construct(accounts_path=accounts_path)
    assert settings.is_configured is True


def test_kitvending_require_configured_for_ingestion_raises_when_file_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounts_path = tmp_path / "kit_platform_accounts.json"
    accounts_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("KIT_PLATFORM_ACCOUNTS_PATH", str(accounts_path))
    monkeypatch.setenv("SALES_INGESTION_ENABLED", "true")
    settings = KitVendingSettings()
    with pytest.raises(ValueError, match="SALES_INGESTION_ENABLED"):
        settings.require_configured_for_ingestion()


def test_kitvending_default_base_url() -> None:
    settings = KitVendingSettings()
    assert "kit-invest.ru" in settings.api_base_url


def test_kitvending_poll_interval_rejects_below_60(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SALES_INGEST_POLL_INTERVAL_SECONDS", "59")
    with pytest.raises(ValidationError):
        KitVendingSettings()


@pytest.mark.parametrize(
    ("env_key", "env_value"),
    [
        ("KITVENDING_CATALOG_CACHE_TTL_SECONDS", "59"),
        ("KITVENDING_REQUESTS_PER_WINDOW", "0"),
        ("KITVENDING_WINDOW_SECONDS", "0"),
        ("KITVENDING_BACKOFF_SECONDS", "0"),
        ("KITVENDING_INITIAL_LOOKBACK_DAYS", "0"),
        ("KITVENDING_INITIAL_LOOKBACK_DAYS", "91"),
    ],
)
def test_kitvending_rejects_invalid_numeric_bounds(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str,
    env_value: str,
) -> None:
    monkeypatch.setenv(env_key, env_value)
    with pytest.raises(ValidationError):
        KitVendingSettings()
