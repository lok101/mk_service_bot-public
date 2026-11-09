from __future__ import annotations

import pytest

from src.config.kitshop import KitShopSettings


def test_kitshop_settings_defaults() -> None:
    s = KitShopSettings()
    assert s.api_base_url == "https://api.kitshop.ru/APIService.svc"
    assert s.requests_per_window == 1
    assert s.window_seconds == 6.0
    assert s.backoff_seconds == 60.0
    assert s.max_consecutive_high_requests == 3
    assert s.reference_refresh_interval_seconds == 3600
    assert s.ingestion_enabled is False


def test_kitshop_max_consecutive_high_default_three() -> None:
    assert KitShopSettings().max_consecutive_high_requests == 3


def test_kitshop_window_seconds_must_be_positive() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        KitShopSettings(window_seconds=0)


def test_kitshop_sale_alert_cooldown_default_is_60() -> None:
    # happy
    assert KitShopSettings().sale_alert_cooldown_minutes == 60


def test_kitshop_sale_alert_cooldown_rejects_zero() -> None:
    # error: ge=1
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        KitShopSettings(sale_alert_cooldown_minutes=0)


def test_kitshop_initial_lookback_days_default_stays_7() -> None:
    # happy: окно первого догона этот фрагмент не меняет
    assert KitShopSettings().initial_lookback_days == 7


def test_kitshop_catalog_ensure_on_publish_default_false() -> None:
    assert KitShopSettings().catalog_ensure_on_publish_enabled is False


def test_kitshop_catalog_ensure_on_publish_reads_env_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KITSHOP_CATALOG_ENSURE_ON_PUBLISH_ENABLED", "true")
    assert KitShopSettings().catalog_ensure_on_publish_enabled is True


def test_kitshop_tls_allow_expired_peer_certificate_default_false() -> None:
    assert KitShopSettings().tls_allow_expired_peer_certificate is False


def test_kitshop_tls_allow_expired_peer_certificate_reads_env_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KITSHOP_TLS_ALLOW_EXPIRED_PEER_CERTIFICATE", "true")
    assert KitShopSettings().tls_allow_expired_peer_certificate is True


def test_kitshop_tls_allow_expired_peer_certificate_reads_env_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KITSHOP_TLS_ALLOW_EXPIRED_PEER_CERTIFICATE", "false")
    assert KitShopSettings().tls_allow_expired_peer_certificate is False
