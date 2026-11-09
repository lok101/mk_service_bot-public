from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config.http_limits import HttpLimitsSettings


def test_http_limits_defaults_one_mebibyte() -> None:
    settings = HttpLimitsSettings()
    assert settings.admin_max_body_bytes == 1_048_576
    assert settings.telegram_webhook_max_body_bytes == 1_048_576


def test_http_limits_rejects_non_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_MAX_BODY_BYTES", "0")
    with pytest.raises(ValidationError):
        HttpLimitsSettings()
    monkeypatch.delenv("ADMIN_MAX_BODY_BYTES", raising=False)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_MAX_BODY_BYTES", "-1")
    with pytest.raises(ValidationError):
        HttpLimitsSettings()
