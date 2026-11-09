from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from src.config.service_calendar import ServiceCalendarSettings
from src.domain.calendar import calendar_day_in_timezone, service_timezone_label


def test_service_calendar_settings_default_timezone() -> None:
    settings = ServiceCalendarSettings()

    assert settings.display_timezone == "Europe/Moscow"
    assert settings.zone_info() == ZoneInfo("Europe/Moscow")


def test_service_calendar_settings_rejects_empty_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SERVICE_DISPLAY_TIMEZONE", raising=False)

    with pytest.raises(ValueError, match="must not be empty"):
        ServiceCalendarSettings(display_timezone="   ")


def test_service_calendar_settings_rejects_invalid_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SERVICE_DISPLAY_TIMEZONE", raising=False)

    with pytest.raises(ValueError, match="not a valid IANA timezone"):
        ServiceCalendarSettings(display_timezone="Not/A/Timezone")


def test_calendar_day_in_timezone_uses_configured_zone() -> None:
    from datetime import UTC, datetime

    value = datetime(2026, 5, 15, 22, 0, tzinfo=UTC)
    moscow_day = calendar_day_in_timezone(value, ZoneInfo("Europe/Moscow"))
    utc_day = calendar_day_in_timezone(value, ZoneInfo("UTC"))

    assert moscow_day.isoformat() == "2026-05-16"
    assert utc_day.isoformat() == "2026-05-15"


def test_service_timezone_label_for_moscow() -> None:
    assert service_timezone_label(ZoneInfo("Europe/Moscow")) == "МСК"


def test_service_day_end_hour_default_six() -> None:
    settings = ServiceCalendarSettings()
    assert settings.service_day_end_hour == 6


def test_service_day_end_hour_rejects_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERVICE_DAY_END_HOUR", "24")
    with pytest.raises(ValidationError):
        ServiceCalendarSettings()
