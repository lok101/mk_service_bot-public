from __future__ import annotations

import time

import pytest

from src.interfaces.google_forms.rate_limit import InMemoryWebhookRateLimiter


def test_rate_limiter_allows_requests_within_window(monkeypatch: pytest.MonkeyPatch) -> None:
    current = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: current[0])

    limiter = InMemoryWebhookRateLimiter(max_requests=2, window_seconds=60.0)
    assert limiter.check("1.2.3.4") is True
    assert limiter.check("1.2.3.4") is True
    assert limiter.check("1.2.3.4") is False


def test_rate_limiter_window_expiry_resets_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    current = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: current[0])

    limiter = InMemoryWebhookRateLimiter(max_requests=1, window_seconds=10.0)
    assert limiter.check("1.2.3.4") is True
    assert limiter.check("1.2.3.4") is False

    current[0] = 11.0
    assert limiter.check("1.2.3.4") is True


def test_rate_limiter_tracks_ips_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    current = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: current[0])

    limiter = InMemoryWebhookRateLimiter(max_requests=1, window_seconds=60.0)
    assert limiter.check("1.1.1.1") is True
    assert limiter.check("1.1.1.1") is False
    assert limiter.check("2.2.2.2") is True


def test_rate_limiter_buckets_unknown_client_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    current = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: current[0])

    limiter = InMemoryWebhookRateLimiter(max_requests=1, window_seconds=60.0)
    assert limiter.check("unknown") is True
    assert limiter.check("unknown") is False


def test_rate_limiter_prunes_expired_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    current = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: current[0])

    limiter = InMemoryWebhookRateLimiter(
        max_requests=10,
        window_seconds=10.0,
        max_tracked_ips=100,
    )
    for index in range(60):
        assert limiter.check(f"ip-{index}") is True

    current[0] = 20.0
    assert limiter.check("ip-new") is True
    assert len(limiter._buckets) == 1


def test_rate_limiter_evicts_oldest_ip_at_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    current = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: current[0])

    limiter = InMemoryWebhookRateLimiter(
        max_requests=100,
        window_seconds=60.0,
        max_tracked_ips=3,
    )
    limiter.check("a")
    limiter.check("b")
    limiter.check("c")
    limiter.check("d")

    assert "a" not in limiter._buckets
    assert "d" in limiter._buckets


def test_rate_limiter_retry_after_seconds() -> None:
    limiter = InMemoryWebhookRateLimiter(max_requests=1, window_seconds=45.7)
    assert limiter.retry_after_seconds == 45
