from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.reference_data import ReferenceDataSettings


def test_defaults_are_valid() -> None:
    settings = ReferenceDataSettings()
    assert settings.sync_interval_seconds == 300
    assert settings.staleness_alert_seconds == 1800


def test_custom_values_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFERENCE_DATA_SYNC_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("REFERENCE_DATA_STALENESS_ALERT_SECONDS", "120")
    settings = ReferenceDataSettings()
    assert settings.sync_interval_seconds == 60
    assert settings.staleness_alert_seconds == 120


def test_sync_interval_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFERENCE_DATA_SYNC_INTERVAL_SECONDS", "0")
    with pytest.raises(ValidationError):
        ReferenceDataSettings()


def test_staleness_must_not_be_below_sync_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REFERENCE_DATA_SYNC_INTERVAL_SECONDS", "300")
    monkeypatch.setenv("REFERENCE_DATA_STALENESS_ALERT_SECONDS", "100")
    with pytest.raises(ValidationError):
        ReferenceDataSettings()
