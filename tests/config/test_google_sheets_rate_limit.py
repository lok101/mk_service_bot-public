from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.google_sheets import GoogleSheetsSettings


def test_rate_limit_defaults() -> None:
    # happy
    s = GoogleSheetsSettings()
    assert s.rate_limit_requests_per_window == 50
    assert s.rate_limit_window_seconds == 60.0
    assert s.rate_limit_backoff_seconds == 60.0


def test_rate_limit_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    # happy
    monkeypatch.setenv("GOOGLE_SHEETS_RATE_LIMIT_REQUESTS_PER_WINDOW", "10")
    monkeypatch.setenv("GOOGLE_SHEETS_RATE_LIMIT_WINDOW_SECONDS", "5.5")
    monkeypatch.setenv("GOOGLE_SHEETS_RATE_LIMIT_BACKOFF_SECONDS", "30.0")
    s = GoogleSheetsSettings()
    assert s.rate_limit_requests_per_window == 10
    assert s.rate_limit_window_seconds == 5.5
    assert s.rate_limit_backoff_seconds == 30.0


def test_rate_limit_requests_per_window_must_be_at_least_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # error
    monkeypatch.setenv("GOOGLE_SHEETS_RATE_LIMIT_REQUESTS_PER_WINDOW", "0")
    with pytest.raises(ValidationError):
        GoogleSheetsSettings()


def test_rate_limit_window_seconds_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    # error
    monkeypatch.setenv("GOOGLE_SHEETS_RATE_LIMIT_WINDOW_SECONDS", "0")
    with pytest.raises(ValidationError):
        GoogleSheetsSettings()
