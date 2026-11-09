from __future__ import annotations

import pytest

from src.config.service_rules import ServiceRulesSettings


def test_revision_interval_defaults() -> None:
    settings = ServiceRulesSettings()
    assert settings.revision_interval_min_days == 10
    assert settings.revision_interval_max_days == 12


def test_revision_grace_days_field_removed() -> None:
    # happy: settings load without grace field
    settings = ServiceRulesSettings()
    assert "revision_grace_days" not in ServiceRulesSettings.model_fields
    assert not hasattr(settings, "revision_grace_days")


def test_unknown_revision_grace_days_env_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # edge: unknown REVISION_GRACE_DAYS ignored by pydantic extra
    monkeypatch.setenv("REVISION_GRACE_DAYS", "5")
    settings = ServiceRulesSettings()
    assert settings.revision_interval_min_days == 10
    assert "revision_grace_days" not in ServiceRulesSettings.model_fields


def test_legacy_revision_interval_days_sets_min_and_max(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVISION_INTERVAL_DAYS", "30")
    settings = ServiceRulesSettings()
    assert settings.revision_interval_min_days == 30
    assert settings.revision_interval_max_days == 30


def test_loading_photos_max_count_defaults_to_ten() -> None:
    settings = ServiceRulesSettings()
    assert settings.loading_photos_max_count == 10


def test_loading_photos_max_count_must_not_exceed_ten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOADING_PHOTOS_MAX_COUNT", "11")
    with pytest.raises(ValueError, match="LOADING_PHOTOS_MAX_COUNT"):
        ServiceRulesSettings()


def test_loading_photos_max_count_must_be_at_least_min_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOADING_PHOTOS_MIN_COUNT", "5")
    monkeypatch.setenv("LOADING_PHOTOS_MAX_COUNT", "3")
    with pytest.raises(ValueError, match="LOADING_PHOTOS_MAX_COUNT"):
        ServiceRulesSettings()


def test_maintenance_cooldown_minutes_defaults_to_twenty() -> None:
    settings = ServiceRulesSettings()
    assert settings.maintenance_cooldown_minutes == 20


def test_maintenance_cooldown_minutes_zero_disables_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAINTENANCE_COOLDOWN_MINUTES", "0")
    settings = ServiceRulesSettings()
    assert settings.maintenance_cooldown_minutes == 0


def test_maintenance_cooldown_minutes_must_not_be_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAINTENANCE_COOLDOWN_MINUTES", "-1")
    with pytest.raises(ValueError, match="MAINTENANCE_COOLDOWN_MINUTES"):
        ServiceRulesSettings()
