from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.moysklad import MoySkladSettings


def test_moysklad_settings_request_defaults() -> None:
    settings = MoySkladSettings.model_construct(api_token=None)
    assert settings.request_timeout_seconds == 30
    assert settings.request_attempts == 3


def test_moysklad_settings_demand_agent_defaults() -> None:
    settings = MoySkladSettings.model_construct(api_token=None)
    assert settings.demand_agent_id == ""


def test_moysklad_rate_limit_defaults() -> None:
    # happy
    settings = MoySkladSettings.model_construct(api_token=None)
    assert settings.rate_limit_requests_per_window == 15
    assert settings.rate_limit_window_seconds == 3.0
    assert settings.rate_limit_backoff_seconds == 60.0
    assert settings.http_max_in_flight == 2
    assert settings.http_max_consecutive_high == 3


def test_moysklad_rate_limit_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    # happy
    monkeypatch.setenv("MOYSKLAD_RATE_LIMIT_REQUESTS_PER_WINDOW", "10")
    monkeypatch.setenv("MOYSKLAD_RATE_LIMIT_WINDOW_SECONDS", "1.5")
    monkeypatch.setenv("MOYSKLAD_RATE_LIMIT_BACKOFF_SECONDS", "30")
    monkeypatch.setenv("MOYSKLAD_HTTP_MAX_IN_FLIGHT", "3")
    monkeypatch.setenv("MOYSKLAD_HTTP_MAX_CONSECUTIVE_HIGH", "2")
    settings = MoySkladSettings()
    assert settings.rate_limit_requests_per_window == 10
    assert settings.rate_limit_window_seconds == 1.5
    assert settings.rate_limit_backoff_seconds == 30.0
    assert settings.http_max_in_flight == 3
    assert settings.http_max_consecutive_high == 2


def test_moysklad_http_max_in_flight_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    # error
    monkeypatch.setenv("MOYSKLAD_HTTP_MAX_IN_FLIGHT", "0")
    with pytest.raises(ValidationError):
        MoySkladSettings()
